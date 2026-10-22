<?php
/* Executed through authenticated SSH on OPNsense; no router credentials are stored.
 * Use the native model, validation, locking, revision history and service reload.
 */
require_once('/usr/local/opnsense/mvc/script/load_phalcon.php');

use OPNsense\Core\Config;
use OPNsense\Unbound\Unbound;

$input = json_decode(stream_get_contents(STDIN), true, 512, JSON_THROW_ON_ERROR);
$action = $input['action'];
$manifest = $input['manifest'];
if (!in_array($action, ['plan', 'apply', 'remove'], true) || !in_array(
    [$manifest['domain'], $manifest['address']],
    [['vm.internal', '10.69.0.1'], ['dalebox.pw', '10.69.0.1']], true
)) {
    throw new RuntimeException('Unexpected DNS provisioning target');
}
$config = Config::getInstance();
$config->lock();
try {
    $model = new Unbound();
    $existing = [];
    foreach ($model->hosts->host->iterateItems() as $uuid => $node) {
        $fqdn = strtolower((string)$node->hostname . '.' . (string)$node->domain);
        if (isset($existing[$fqdn])) {
            throw new RuntimeException('Duplicate existing host override: ' . $fqdn);
        }
        $existing[$fqdn] = $node;
    }
    $changes = [];
    foreach ($manifest['services'] as $name => $port) {
        if (!preg_match('/^[a-z][a-z0-9-]*$/', $name) || !is_int($port) || $port < 1 || $port > 65535) {
            throw new RuntimeException('Invalid service manifest');
        }
        $fqdn = $name . '.' . $manifest['domain'];
        $description = 'nixflix managed Caddy route: ' . $name;
        $node = $existing[$fqdn] ?? null;
        if ($node !== null && (string)$node->description !== $description) {
            throw new RuntimeException('Refusing to replace unmanaged DNS override: ' . $fqdn);
        }
        // A pre-existing alias may otherwise silently shadow the new host.
        foreach ($model->aliases->alias->iterateItems() as $alias) {
            if (strtolower((string)$alias->hostname . '.' . (string)$alias->domain) === $fqdn) {
                throw new RuntimeException('Conflicting existing DNS alias: ' . $fqdn);
            }
        }
        if ($action === 'remove') {
            if ($node !== null) {
                $model->hosts->host->del($node->getAttribute('uuid'));
                $changes[] = ['name' => $fqdn, 'action' => 'remove'];
            }
            continue;
        }
        $values = ['enabled' => '1', 'hostname' => $name, 'domain' => $manifest['domain'],
                   'rr' => 'A', 'server' => $manifest['address'], 'ttl' => '60',
                   'addptr' => '0', 'description' => $description];
        $different = $node === null;
        if ($node !== null) {
            foreach ($values as $field => $value) {
                $different = $different || (string)$node->{$field} !== $value;
            }
        }
        if ($different) {
            $changes[] = ['name' => $fqdn, 'action' => $node === null ? 'add' : 'update',
                          'address' => $manifest['address']];
            $node ??= $model->hosts->host->Add();
            $node->setNodes($values);
        }
    }
    $messages = $model->performValidation();
    if (count($messages) > 0) {
        $errors = [];
        foreach ($messages as $message) $errors[] = (string)$message;
        throw new RuntimeException('DNS model validation failed: ' . implode('; ', $errors));
    }
    if ($action !== 'plan' && count($changes) > 0) {
        $backupDir = '/conf/nixflix-dns-backups';
        if (!is_dir($backupDir) && !mkdir($backupDir, 0700)) {
            throw new RuntimeException('Unable to create protected backup directory');
        }
        $backup = $backupDir . '/config-' . gmdate('Ymd-His') . '-' . bin2hex(random_bytes(3)) . '.xml';
        if (!copy('/conf/config.xml', $backup) || !chmod($backup, 0600)) {
            throw new RuntimeException('Unable to save router configuration backup');
        }
        $model->serializeToConfig();
        $config->save('Nixflix managed Caddy DNS: ' . $action);
    }
} finally {
    $config->unlock();
}
echo json_encode(['action' => $action, 'changes' => $changes, 'backup' => $backup ?? null], JSON_PRETTY_PRINT) . "\n";
if ($action !== 'plan' && count($changes) > 0) {
    passthru('/usr/local/sbin/configctl unbound restart', $code);
    if ($code !== 0) throw new RuntimeException('Unbound reload failed; inspect protected backup before proceeding');
}
