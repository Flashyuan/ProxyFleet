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

proxyfleet-managed-dir:
  file.directory:
    - name: /etc/proxyfleet/managed
    - user: root
    - group: root
    - mode: '0750'
    - require:
      - file: proxyfleet-install-root

proxyfleet-local-dir:
  file.directory:
    - name: /etc/proxyfleet/local
    - user: root
    - group: root
    - mode: '0750'
    - require:
      - file: proxyfleet-install-root

proxyfleet-effective-dir:
  file.directory:
    - name: /etc/proxyfleet/effective
    - user: root
    - group: root
    - mode: '0750'
    - require:
      - file: proxyfleet-install-root

{% if pillar.get('proxyfleet_port_policy_enabled', False) %}
proxyfleet-managed-port-policy:
  file.managed:
    - name: /etc/proxyfleet/managed/port-policy.yaml
    - source: salt://proxyfleet/port-policy.yaml
    - user: root
    - group: root
    - mode: '0640'
    - require:
      - file: proxyfleet-managed-dir

proxyfleet-effective-port-policy:
  module.run:
    - name: proxyfleet_mihomo.apply_port_policy
    - managed_path: /etc/proxyfleet/managed/port-policy.yaml
    - local_path: /etc/proxyfleet/local/port-policy.yaml
    - effective_path: /etc/proxyfleet/effective/port-policy.yaml
    - mode: {{ pillar.get('proxyfleet_port_policy_mode', 'merge') }}
    - operation_id: {{ pillar.get('proxyfleet_operation_id', 'op-unknown') }}
    - fail_on_error: true
    - require:
      - file: proxyfleet-managed-port-policy
      - file: proxyfleet-local-dir
      - file: proxyfleet-effective-dir
{% endif %}

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
    - fail_on_error: true
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
    - fail_on_error: true
    - require:
      - module: proxyfleet-install-mihomo
{% if pillar.get('proxyfleet_port_policy_enabled', False) %}
      - module: proxyfleet-effective-port-policy
{% endif %}
