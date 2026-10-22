<?php
/* Native DNAT rules: web traffic to router Caddy, Plex clients to the VM. */
require_once('/usr/local/opnsense/mvc/script/load_phalcon.php');
use OPNsense\Core\Config;
use OPNsense\Firewall\DNat;
use OPNsense\Dnsmasq\Dnsmasq;
$input = json_decode(stream_get_contents(STDIN), true, 512, JSON_THROW_ON_ERROR);
$action = $input['action'];
if (!in_array($action, ['ingress-plan','ingress-apply'], true)) throw new RuntimeException('Unexpected ingress action');
$manifest = $input['manifest'];
if ($manifest['address'] !== '10.69.0.18' || !preg_match('/^([0-9a-f]{2}:){5}[0-9a-f]{2}$/', $manifest['macAddress'])) {
    throw new RuntimeException('Unexpected DHCP reservation target');
}
$config = Config::getInstance();
$config->lock();
$changes = [];
try {
    $model = new DNat();
    foreach ([80=>'10.69.0.1',443=>'10.69.0.1',32400=>'10.69.0.18'] as $port=>$target) {
        $description = $port === 32400 ? 'Plex Port Forward' : 'nixflix managed Caddy WAN ' . $port;
        $match = null;
        foreach ($model->rule->iterateItems() as $node) {
            if ((string)$node->descr === $description) {
                if ($match !== null) throw new RuntimeException('Duplicate managed port forward');
                $match = $node;
            } elseif ((string)$node->interface === 'wan' && (string)$node->destination->port === (string)$port && (string)$node->disabled !== '1') {
                throw new RuntimeException('Existing conflicting WAN port forward requires review');
            }
        }
        $values = ['disabled'=>'0','nordr'=>'0','interface'=>'wan','ipprotocol'=>'inet',
            'protocol'=>'tcp','target'=>$target,'local-port'=>(string)$port,'descr'=>$description,
            'pass'=>'pass','associated-rule-id'=>'','natreflection'=>'disable'];
        if ($match === null) {
            $match = $model->rule->Add();
            $match->sequence = (string)$port;
            $changes[] = 'add ' . $description;
        }
        foreach ($values as $field=>$value) if ((string)$match->{$field} !== $value) {
            $match->{$field} = $value;
            $changes[] = $description . ': ' . $field;
        }
        foreach (['network'=>'','port'=>'','not'=>'0'] as $field=>$value) if ((string)$match->source->{$field} !== $value) {
            $match->source->{$field} = $value;
            $changes[] = $description . ': source.' . $field;
        }
        foreach (['network'=>'wanip','port'=>(string)$port,'not'=>'0'] as $field=>$value) if ((string)$match->destination->{$field} !== $value) {
            $match->destination->{$field} = $value;
            $changes[] = $description . ': destination.' . $field;
        }
    }
    $natChanged = count($changes) > 0;
    $dhcp = new Dnsmasq();
    $description = 'nixflix managed VM address reservation';
    $reservation = null;
    foreach ($dhcp->hosts->iterateItems() as $node) {
        if ((string)$node->descr === $description) {
            if ($reservation !== null) throw new RuntimeException('Duplicate managed DHCP reservation');
            $reservation = $node;
        } elseif (in_array($manifest['address'], $node->ip->getValues(), true) ||
                  in_array($manifest['macAddress'], $node->hwaddr->getValues(), true) ||
                  ((string)$node->host === 'nixflix' && (string)$node->domain === 'vm.internal')) {
            throw new RuntimeException('Conflicting unmanaged DHCP reservation requires review');
        }
    }
    $dhcpChanged = $reservation === null;
    $reservation ??= $dhcp->hosts->Add();
    foreach (['host'=>'nixflix', 'domain'=>'vm.internal', 'ip'=>$manifest['address'],
              'hwaddr'=>$manifest['macAddress'], 'ignore'=>'0', 'local'=>'0',
              'client_id'=>'', 'lease_time'=>'86400', 'descr'=>$description] as $field=>$value) {
        if ((string)$reservation->{$field} !== $value) {
            $reservation->{$field} = $value;
            $dhcpChanged = true;
        }
    }
    if ($dhcpChanged) $changes[] = $description;
    foreach ([$model, $dhcp] as $validated) {
        $messages = $validated->performValidation();
        if (count($messages)) {
            $errors=[]; foreach($messages as $message)$errors[]=$message->getField().': '.(string)$message;
            throw new RuntimeException(implode('; ',$errors));
        }
    }
    if ($action === 'ingress-apply' && count($changes)) {
        $directory='/conf/nixflix-https-backups';
        if (!is_dir($directory)) mkdir($directory,0700);
        $backup=$directory.'/ingress-'.gmdate('Ymd-His').'-'.bin2hex(random_bytes(3)).'.xml';
        if (!copy('/conf/config.xml',$backup)||!chmod($backup,0600)) throw new RuntimeException('Backup failed');
        $model->serializeToConfig();
        $dhcp->serializeToConfig();
        $config->save('Nixflix WAN HTTPS and Plex remote access');
    }
} finally { $config->unlock(); }
echo json_encode(['action'=>$action,'changes'=>$changes,'backup'=>$backup??null],JSON_PRETTY_PRINT)."\n";
if ($action === 'ingress-apply' && $dhcpChanged) {
    passthru('/usr/local/sbin/configctl dnsmasq restart', $code);
    if ($code !== 0) throw new RuntimeException('Native DHCP reload failed');
}
if ($action === 'ingress-apply' && $natChanged) {
    passthru('/usr/local/sbin/configctl filter reload', $code);
    if ($code !== 0) throw new RuntimeException('Native filter reload failed');
}
