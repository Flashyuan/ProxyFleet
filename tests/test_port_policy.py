import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from proxyfleet.cli import main
from proxyfleet.port_policy import PortPolicyError, build_effective_policy, status


class PortPolicyTests(unittest.TestCase):
    def test_merge_managed_and_local_keeps_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            managed = root / "managed.json"
            local = root / "local.json"
            effective = root / "effective.json"
            managed.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "owner": "master",
                        "allow": [{"protocol": "tcp", "port": 22, "source": "192.168.1.0/24"}],
                        "deny": [],
                    }
                ),
                encoding="utf-8",
            )
            local.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "owner": "local",
                        "allow": [{"protocol": "tcp", "port": 8080, "source": "any"}],
                        "deny": [],
                    }
                ),
                encoding="utf-8",
            )

            result = build_effective_policy(managed, local, effective, mode="merge")
            data = json.loads(effective.read_text(encoding="utf-8"))

            self.assertEqual(2, result.rule_count)
            self.assertEqual(["master", "local"], [rule["owner"] for rule in data["allow"]])

    def test_conflict_does_not_overwrite_existing_effective(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            managed = root / "managed.json"
            local = root / "local.json"
            effective = root / "effective.json"
            effective.write_text('{"schema_version":"1.0","owner":"effective","allow":[],"deny":[]}\n', encoding="utf-8")
            before = effective.read_text(encoding="utf-8")
            managed.write_text(
                json.dumps({"owner": "master", "allow": [{"protocol": "tcp", "port": 22, "source": "any"}], "deny": []}),
                encoding="utf-8",
            )
            local.write_text(
                json.dumps({"owner": "local", "allow": [], "deny": [{"protocol": "tcp", "port": 22, "source": "any"}]}),
                encoding="utf-8",
            )

            with self.assertRaises(PortPolicyError) as ctx:
                build_effective_policy(managed, local, effective, mode="merge")

            self.assertEqual("E_PORT_POLICY_CONFLICT", ctx.exception.error_code)
            self.assertEqual(before, effective.read_text(encoding="utf-8"))

    def test_master_only_does_not_require_local_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            managed = root / "managed.json"
            local = root / "missing-local.json"
            effective = root / "effective.json"
            managed.write_text(
                json.dumps({"owner": "master", "allow": [{"protocol": "udp", "port": 53, "source": "any"}], "deny": []}),
                encoding="utf-8",
            )

            result = build_effective_policy(managed, local, effective, mode="master-only")
            state = status(managed, local, effective, mode="master-only")

            self.assertEqual(1, result.rule_count)
            self.assertFalse(state["local_exists"])
            self.assertTrue(state["effective_exists"])

    def test_cli_port_policy_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            managed = root / "managed.json"
            local = root / "local.json"
            effective = root / "effective.json"
            managed.write_text(json.dumps({"owner": "master", "allow": [], "deny": []}), encoding="utf-8")
            local.write_text(json.dumps({"owner": "local", "allow": [], "deny": []}), encoding="utf-8")

            with mock.patch("sys.stdout"):
                rc = main(["port-policy", "build", str(managed), str(local), str(effective)])

            self.assertEqual(0, rc)
            self.assertTrue(effective.exists())

    def test_schema_version_must_be_supported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            managed = root / "managed.json"
            local = root / "local.json"
            effective = root / "effective.json"
            managed.write_text(json.dumps({"schema_version": "2.0", "owner": "master", "allow": [], "deny": []}), encoding="utf-8")
            local.write_text(json.dumps({"owner": "local", "allow": [], "deny": []}), encoding="utf-8")

            with self.assertRaises(PortPolicyError) as ctx:
                build_effective_policy(managed, local, effective)

            self.assertEqual("E_PORT_POLICY_SCHEMA", ctx.exception.error_code)

    def test_rule_source_must_be_any_ip_or_cidr(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            managed = root / "managed.json"
            local = root / "local.json"
            effective = root / "effective.json"
            managed.write_text(
                json.dumps({"owner": "master", "allow": [{"protocol": "tcp", "port": 22, "source": "office-lan"}], "deny": []}),
                encoding="utf-8",
            )
            local.write_text(json.dumps({"owner": "local", "allow": [], "deny": []}), encoding="utf-8")

            with self.assertRaises(PortPolicyError) as ctx:
                build_effective_policy(managed, local, effective)

            self.assertEqual("E_PORT_POLICY_SCHEMA", ctx.exception.error_code)


if __name__ == "__main__":
    unittest.main()
