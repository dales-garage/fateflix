<?php
/* Router Caddy owns internal CA and selected public-domain certificates. */
require_once('/usr/local/opnsense/mvc/script/load_phalcon.php');

use OPNsense\Core\Config;
use OPNsense\Caddy\Caddy;

$input = json_decode(stream_get_contents(STDIN), true, 512, JSON_THROW_ON_ERROR);
$action = $input['action'];
$manifest = $input['manifest'];
if (!in_array($action, ['plan', 'prepare', 'apply'], true) || $manifest['address'] !== '10.69.0.18' ||
    $manifest['routerAddress'] !== '10.69.0.1' || $manifest['domain'] !== 'vm.internal' ||
    array_intersect($manifest['publicServices'], ['stash','whisparr','sonarr','sonarr-4k','radarr','radarr-4k','sabnzbd','bazarr','bazarr-4k'])) {
    throw new RuntimeException('Unexpected HTTPS provisioning target');
}
$changes = [];
function managed($array, $description, $values, $uniqueField = null) {
    global $changes;
    $match = null;
    foreach ($array->iterateItems() as $node) {
        if ((string)$node->description === $description) {
            if ($match !== null) throw new RuntimeException('Duplicate managed object');
            $match = $node;
        } elseif ($uniqueField !== null && (string)$node->{$uniqueField} === $values[$uniqueField]) {
            throw new RuntimeException('Conflicting unmanaged object: ' . $description);
        }
    }
    $values['description'] = $description;
    $different = $match === null;
    if ($match !== null) foreach ($values as $key => $value) {
        // UpdateOnlyTextField deliberately renders as blank; compare stored data.
        $different = $different || $match->{$key}->getValue() !== $value;
    }
    if ($different) {
        $match ??= $array->Add();
        $match->setNodes($values);
        $changes[] = $description;
    }
    return $match->getAttribute('uuid');
}

$config = Config::getInstance();
$config->lock();
try {
    $model = new Caddy();
    if ($action === 'prepare' && (string)$model->general->enabled === '1') {
        throw new RuntimeException('Use apply to update an active proxy');
    }
    foreach ($model->reverseproxy->reverse->iterateItems() as $node) {
        if ((string)$node->description !== 'nixflix managed public wildcard') {
            throw new RuntimeException('Existing unrelated Caddy domains require review before changing global settings');
        }
    }
    $general = ['TlsDnsProvider'=>'cloudflare',
                'TlsDnsPropagationResolvers'=>'1.1.1.1',
                'TlsAutoHttps'=>'', 'HttpVersions'=>'h1,h2', 'DisableSuperuser'=>'0',
                'DynDnsInterface'=>'wan', 'DynDnsIpVersions'=>'ipv4',
                'DynDnsInterval'=>'300', 'DynDnsTtl'=>'120', 'DynDnsUpdateOnly'=>'1'];
    if ($action === 'apply') {
        if (!preg_match('/^[A-Za-z0-9_-]{20,}$/', $input['dns_token'] ?? '')) {
            throw new RuntimeException('Missing or malformed DNS token');
        }
        $general['TlsDnsApiKey'] = $input['dns_token'];
        $general['enabled'] = '1';
    }
    foreach ($general as $key => $value) {
        if ((string)$model->general->{$key} !== $value) {
            $model->general->{$key} = $value;
            $changes[] = 'general.' . $key;
        }
    }
    $access = managed($model->reverseproxy->accesslist, 'nixflix managed LAN access', [
        'accesslistName'=>'nixflix_lans', 'clientIps'=>'10.69.0.0/24,10.42.0.0/24',
        'RequestMatcher'=>'remote_ip', 'HttpResponseCode'=>'403',
        'HttpResponseMessage'=>'LAN access only', 'accesslistInvert'=>'0',
    ], 'accesslistName');
    $wildcard = managed($model->reverseproxy->reverse, 'nixflix managed public wildcard', [
        'enabled'=>'1', 'FromDomain'=>'*.dalebox.pw', 'DisableTls'=>'0',
        'DnsChallenge'=>'1', 'DynDns'=>'0', 'accesslist'=>'',
    ], 'FromDomain');
    $auth = null;
    foreach ($model->reverseproxy->basicauth->iterateItems() as $node) {
        if ((string)$node->description === 'nixflix managed public dashboard login') $auth = $node;
    }
    if ($action === 'apply') {
        $password = $input['web_password'] ?? '';
        if (strlen($password) < 24) throw new RuntimeException('Missing public dashboard credential');
        $hash = $auth !== null ? $auth->basicauthpass->getValue() : '';
        if (!password_verify($password, $hash)) $hash = password_hash($password, PASSWORD_BCRYPT);
        $authId = managed($model->reverseproxy->basicauth, 'nixflix managed public dashboard login', [
            'basicauthuser'=>'nixflix', 'basicauthpass'=>$hash,
        ], 'basicauthuser');
    } elseif ($auth !== null) {
        $authId = $auth->getAttribute('uuid');
    } else {
        // A non-credential placeholder supports model-only planning; never saved.
        $authId = managed($model->reverseproxy->basicauth, 'nixflix managed public dashboard login', [
            'basicauthuser'=>'nixflix', 'basicauthpass'=>password_hash('planning-only-not-a-live-password', PASSWORD_BCRYPT),
        ], 'basicauthuser');
        if ($action === 'prepare') throw new RuntimeException('Initial authenticated public setup requires apply');
    }
    // Retire previously prepared public routes now explicitly excluded by policy.
    foreach (['handle'=>'nixflix managed public upstream: ', 'subdomain'=>'nixflix managed public name: '] as $group=>$prefix) {
        $remove = [];
        foreach ($model->reverseproxy->{$group}->iterateItems() as $uuid=>$node) {
            $description = (string)$node->description;
            if (str_starts_with($description, $prefix) && !in_array(substr($description, strlen($prefix)), $manifest['publicServices'], true)) {
                $remove[] = $uuid;
                $changes[] = 'remove ' . $description;
            }
        }
        foreach ($remove as $uuid) $model->reverseproxy->{$group}->del($uuid);
    }
    foreach ($manifest['services'] as $name => $port) {
        if (!preg_match('/^[a-z][a-z0-9-]*$/', $name) || !is_int($port) || $port < 1 || $port > 65535) {
            throw new RuntimeException('Invalid service manifest');
        }
        if (!in_array($name, $manifest['publicServices'], true)) continue;
        $subdomain = managed($model->reverseproxy->subdomain, 'nixflix managed public name: ' . $name, [
            'enabled'=>'1', 'reverse'=>$wildcard,
            'FromDomain'=>($manifest['publicNames'][$name] ?? $name) . '.dalebox.pw', 'DynDns'=>'1',
            'basicauth'=>in_array($name, $manifest['publicAuthServices'], true) ? $authId : '',
        ], 'FromDomain');
        managed($model->reverseproxy->handle, 'nixflix managed public upstream: ' . $name, [
            'enabled'=>'1', 'reverse'=>$wildcard, 'subdomain'=>$subdomain,
            'HandleType'=>'handle', 'HandleDirective'=>'reverse_proxy',
            'ToDomain'=>$manifest['address'], 'ToPort'=>(string)$port, 'HttpTls'=>'0',
        ]);
    }
    // Refresh native relation caches after adding related objects in one batch.
    foreach (['reverse', 'subdomain', 'handle'] as $group) {
        foreach ($model->reverseproxy->{$group}->iterateItems() as $uuid => $node) {
            foreach (['accesslist', 'reverse', 'subdomain', 'basicauth'] as $field) {
                $relation = $model->getNodeByReference('reverseproxy.' . $group . '.' . $uuid . '.' . $field);
                if ($relation instanceof OPNsense\Base\FieldTypes\ModelRelationField) {
                    $relation->getCachedData(Caddy::class, 'reverseproxy.' . $field, true);
                }
            }
        }
    }
    $messages = $model->performValidation();
    if (count($messages) > 0) {
        $errors = [];
        foreach ($messages as $message) $errors[] = $message->getField() . ': ' . (string)$message;
        throw new RuntimeException('Caddy model validation failed: ' . implode('; ', $errors));
    }
    // OPNsense documents these custom imports for binding to a static interface.
    // Explicit HTTP bind avoids automatic redirects listening on the GUI address.
    $files = [
        '/usr/local/etc/caddy/caddy.d/nixflix-bind.global'=>"# Managed by declarative-dale/nixflix\ndefault_bind 10.69.0.1\n",
        '/usr/local/etc/caddy/caddy.d/nixflix-bind.conf'=>"# Managed by declarative-dale/nixflix\nhttp:// {\n bind 10.69.0.1\n}\n",
    ];
    $internal = "# Managed by declarative-dale/nixflix\n";
    foreach ($manifest['services'] as $name=>$port) {
        $internal .= "https://{$name}.vm.internal {\n tls internal\n" .
            " @denied not remote_ip 10.69.0.0/24 10.42.0.0/24\n respond @denied 403\n" .
            " reverse_proxy http://10.69.0.18:{$port} {\n header_down Location ^http:// https://\n }\n}\n";
    }
    $files['/usr/local/etc/caddy/caddy.d/nixflix-internal.conf'] = $internal;
    foreach ($files as $path => $content) {
        if (file_exists($path) && !str_starts_with(file_get_contents($path), '# Managed by declarative-dale/nixflix')) {
            throw new RuntimeException('Existing custom bind file differs; review before replacing: ' . $path);
        }
        if (!file_exists($path) || file_get_contents($path) !== $content) $changes[] = $path;
    }
    if ($action !== 'plan' && count($changes) > 0) {
        $backupDir = '/conf/nixflix-https-backups';
        if (!is_dir($backupDir) && !mkdir($backupDir, 0700)) throw new RuntimeException('Backup directory failed');
        $backup = $backupDir . '/config-' . gmdate('Ymd-His') . '-' . bin2hex(random_bytes(3)) . '.xml';
        if (!copy('/conf/config.xml', $backup) || !chmod($backup, 0600)) throw new RuntimeException('Backup failed');
        $directory = '/usr/local/etc/caddy/caddy.d';
        if (!is_dir($directory) && !mkdir($directory, 0750, true)) throw new RuntimeException('Bind directory failed');
        foreach ($files as $path => $content) {
            if (!file_exists($path) || file_get_contents($path) !== $content) {
                $temporary = tempnam($directory, '.nixflix-');
                if (file_put_contents($temporary, $content) === false || !chmod($temporary, 0640) || !rename($temporary, $path)) {
                    throw new RuntimeException('Atomic bind file installation failed');
                }
            }
        }
        $model->serializeToConfig();
        $config->save('Nixflix router HTTPS: ' . $action);
    }
} finally {
    $config->unlock();
}
echo json_encode(['action'=>$action, 'changes'=>$changes, 'backup'=>$backup ?? null,
    'enabled'=>(string)$model->general->enabled === '1', 'dns_token_present'=>(string)$model->general->TlsDnsApiKey !== '',
    'dns_overrides_published'=>false], JSON_PRETTY_PRINT) . "\n";
if ($action === 'apply') {
    // Keep diagnostics on the router; they may contain configuration details.
    $log = '/conf/nixflix-https-validation.log';
    touch($log); chmod($log, 0600);
    exec('/usr/local/sbin/configctl template reload OPNsense/Caddy >' . escapeshellarg($log) . ' 2>&1', $output, $code);
    if ($code === 0) exec('/usr/local/opnsense/scripts/OPNsense/Caddy/setup.sh >>' . escapeshellarg($log) . ' 2>&1', $output, $code);
    if ($code === 0) exec('/usr/sbin/service caddy oneconfigtest >>' . escapeshellarg($log) . ' 2>&1', $output, $code);
    if ($code !== 0) throw new RuntimeException('Caddy validation failed; inspect protected router log before activation');
    exec('/usr/bin/pgrep -x caddy', $pids, $running);
    $command = $running === 0 ? '/usr/local/sbin/configctl caddy reload' : '/usr/local/sbin/configctl caddy start';
    exec($command . ' >>' . escapeshellarg($log) . ' 2>&1', $output, $code);
    if ($code !== 0) throw new RuntimeException('Caddy activation failed; inspect protected router log');
    exec('/usr/bin/pgrep -x caddy', $pids, $running);
    if ($running !== 0) throw new RuntimeException('Caddy is not running after activation; inspect protected router log');
    echo "Caddy configuration validated and activation requested\n";
}
