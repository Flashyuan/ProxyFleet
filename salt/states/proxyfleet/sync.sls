# ProxyFleet release 与 desired state 同步入口。
#
# Master 侧先执行：
#   proxyfleet publish-salt <release_dir> <desired.yaml> /srv/proxyfleet/salt/states
# 然后执行：
#   proxyfleet sync <release_dir> <desired.yaml> /srv/proxyfleet/salt/states --target '<target>'

proxyfleet-install-root:
  file.directory:
    - name: /etc/proxyfleet
    - user: root
    - group: root
    - mode: '0750'

proxyfleet-component-locks:
  file.managed:
    - name: /etc/proxyfleet/component-locks.json
    - source: salt://proxyfleet/component-locks.json
    - user: root
    - group: root
    - mode: '0600'
    - require:
      - file: proxyfleet-install-root

proxyfleet-install-mihomo:
  module.run:
    - name: proxyfleet_mihomo.install_mihomo
    - component_locks_path: /etc/proxyfleet/component-locks.json
    - binary_path: /usr/local/bin/mihomo
    - service_path: /etc/systemd/system/mihomo.service
    - config_path: /etc/proxyfleet/current/config.yaml
    - operation_id: {{ pillar.get('proxyfleet_operation_id', 'op-unknown') }}
    - require:
      - file: proxyfleet-component-locks

proxyfleet-apply-desired:
  module.run:
    - name: proxyfleet_mihomo.apply_desired
    - release_root: {{ pillar.get('proxyfleet_release_root', '/srv/proxyfleet/salt/states/proxyfleet/releases') }}
    - desired_path: {{ pillar.get('proxyfleet_desired_path', '/srv/proxyfleet/salt/states/proxyfleet/desired.yaml') }}
    - install_root: /etc/proxyfleet
    - mihomo_api: http://127.0.0.1:9090
    - api_secret: null
    - service_name: mihomo.service
    - operation_id: {{ pillar.get('proxyfleet_operation_id', 'op-unknown') }}
    - require:
      - module: proxyfleet-install-mihomo
