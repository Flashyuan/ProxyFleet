import unittest

from proxyfleet.component_locks import validate_lock_data


def minimal_component(**overrides):
    component = {
        "name": "mihomo",
        "kind": "binary",
        "version": "v1.19.27",
        "status": "candidate",
        "architectures": ["linux-amd64"],
        "install_policy": {
            "allow_auto_update": False,
            "require_exact_version": True,
            "hold_after_install": True,
        },
        "integrity": {
            "sha256": None,
        },
    }
    component.update(overrides)
    return component


def lock_with(component):
    return {
        "schema_version": "1.0",
        "generated_at": "2026-06-24T00:00:00Z",
        "policy": {
            "no_floating_versions": True,
            "no_automatic_updates": True,
            "fail_closed_on_missing_integrity": True,
        },
        "components": [component],
    }


class ComponentLockTests(unittest.TestCase):
    def test_candidate_may_defer_binary_hash(self):
        issues = validate_lock_data(lock_with(minimal_component()))
        self.assertEqual([], issues)

    def test_floating_version_is_rejected(self):
        issues = validate_lock_data(lock_with(minimal_component(version="latest")))
        self.assertTrue(any("浮动版本" in issue.message for issue in issues))

    def test_automatic_update_is_rejected(self):
        component = minimal_component(
            install_policy={
                "allow_auto_update": True,
                "require_exact_version": True,
                "hold_after_install": True,
            }
        )
        issues = validate_lock_data(lock_with(component))
        self.assertTrue(any("不得自动更新" in issue.message for issue in issues))

    def test_installable_binary_requires_sha256(self):
        issues = validate_lock_data(lock_with(minimal_component(status="installable")))
        self.assertTrue(any("SHA-256" in issue.message for issue in issues))

    def test_installable_binary_accepts_arch_artifacts(self):
        issues = validate_lock_data(
            lock_with(
                minimal_component(
                    status="installable",
                    artifacts={
                        "linux-amd64": {
                            "url": "https://example.invalid/mihomo.gz",
                            "sha256": "a" * 64,
                            "compression": "gzip",
                            "target_path": "/usr/local/bin/mihomo",
                        }
                    },
                )
            )
        )
        self.assertEqual([], issues)

    def test_installable_artifact_rejects_missing_sha(self):
        issues = validate_lock_data(
            lock_with(
                minimal_component(
                    status="installable",
                    artifacts={
                        "linux-amd64": {
                            "url": "https://example.invalid/mihomo.gz",
                            "compression": "gzip",
                        }
                    },
                )
            )
        )
        self.assertTrue(any("artifacts.linux-amd64.sha256" in issue.path for issue in issues))

    def test_unsupported_schema_major_is_rejected(self):
        data = lock_with(minimal_component())
        data["schema_version"] = "2.0"
        issues = validate_lock_data(data)
        self.assertTrue(any("schema_version" in issue.path for issue in issues))

    def test_generated_at_must_be_rfc3339_utc(self):
        data = lock_with(minimal_component())
        data["generated_at"] = "2026-06-24"
        issues = validate_lock_data(data)
        self.assertTrue(any("generated_at" in issue.path for issue in issues))

    def test_installable_artifacts_must_cover_architectures_exactly(self):
        issues = validate_lock_data(
            lock_with(
                minimal_component(
                    status="installable",
                    architectures=["linux-amd64", "linux-arm64"],
                    artifacts={
                        "linux-amd64": {
                            "url": "https://example.invalid/mihomo.gz",
                            "sha256": "a" * 64,
                            "compression": "gzip",
                        },
                        "linux-riscv64": {
                            "url": "https://example.invalid/mihomo.gz",
                            "sha256": "b" * 64,
                            "compression": "gzip",
                        },
                    },
                )
            )
        )
        self.assertTrue(any("linux-arm64" in issue.path for issue in issues))
        self.assertTrue(any("linux-riscv64" in issue.path for issue in issues))

    def test_installable_artifact_rejects_credential_url_and_unsafe_target(self):
        issues = validate_lock_data(
            lock_with(
                minimal_component(
                    status="installable",
                    artifacts={
                        "linux-amd64": {
                            "url": "https://user:pass@example.invalid/mihomo.gz",
                            "sha256": "a" * 64,
                            "compression": "gzip",
                            "target_path": "/bin/sh",
                        }
                    },
                )
            )
        )
        self.assertTrue(any(issue.path.endswith(".url") for issue in issues))
        self.assertTrue(any(issue.path.endswith(".target_path") for issue in issues))

    def test_source_url_rejects_credentials(self):
        issues = validate_lock_data(lock_with(minimal_component(source="https://user:pass@example.invalid/release")))
        self.assertTrue(any(issue.path.endswith(".source") for issue in issues))

    def test_installable_container_requires_digest(self):
        component = minimal_component(
            name="proxyfleet-salt-master-image",
            kind="container_image",
            status="installable",
            integrity={"digest": "latest"},
        )
        issues = validate_lock_data(lock_with(component))
        self.assertTrue(any("digest" in issue.path for issue in issues))

    def test_architecture_is_required(self):
        component = minimal_component()
        component.pop("architectures")
        issues = validate_lock_data(lock_with(component))
        self.assertTrue(any("architecture" in issue.path for issue in issues))


if __name__ == "__main__":
    unittest.main()
