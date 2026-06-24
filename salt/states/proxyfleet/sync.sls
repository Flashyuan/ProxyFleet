# ProxyFleet release 与 desired state 同步入口。
#
# Master 侧先执行：
#   proxyfleet publish-salt <release_dir> <desired.yaml> /srv/salt
# 然后执行：
#   proxyfleet sync <release_dir> <desired.yaml> /srv/salt --target '<target>'

proxyfleet-apply-desired:
  module.run:
    - name: proxyfleet_mihomo.apply_desired
    - release_root: {{ pillar.get('proxyfleet_release_root', '/srv/salt/proxyfleet/releases') }}
    - desired_path: {{ pillar.get('proxyfleet_desired_path', '/srv/salt/proxyfleet/desired.yaml') }}
    - install_root: /etc/proxyfleet
    - mihomo_api: http://127.0.0.1:9090
    - api_secret: null
    - service_name: mihomo.service
    - operation_id: {{ pillar.get('proxyfleet_operation_id', 'op-unknown') }}
