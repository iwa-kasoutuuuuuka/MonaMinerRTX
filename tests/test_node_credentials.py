"""
Tests for the per-installation RPC password of the bundled node:
    python -m unittest tests.test_node_credentials -v
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.node_credentials import (
    CONF_NAME, DEFAULT_RPC_PASSWORD, TEMPLATE_NAME, ensure_rpc_password, read_rpc_password,
)

REPO_NODE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "node")


class TestEnsureRpcPassword(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.node_dir = self._tmp.name
        self.conf = os.path.join(self.node_dir, CONF_NAME)
        with open(os.path.join(REPO_NODE_DIR, TEMPLATE_NAME), "rb") as src:
            self.template_bytes = src.read()
        with open(os.path.join(self.node_dir, TEMPLATE_NAME), "wb") as dst:
            dst.write(self.template_bytes)

    def tearDown(self):
        self._tmp.cleanup()

    def test_shipped_template_holds_only_the_placeholder(self):
        self.assertEqual(read_rpc_password(os.path.join(REPO_NODE_DIR, TEMPLATE_NAME)), DEFAULT_RPC_PASSWORD)

    def test_first_launch_creates_conf_with_a_random_password(self):
        password, changed = ensure_rpc_password(self.node_dir)
        self.assertTrue(changed)
        self.assertNotEqual(password, DEFAULT_RPC_PASSWORD)
        self.assertGreaterEqual(len(password), 24)
        self.assertEqual(read_rpc_password(self.conf), password)
        # everything else in the conf is the template, and the template itself is untouched
        with open(self.conf, "rb") as f:
            self.assertEqual(f.read().replace(password.encode(), DEFAULT_RPC_PASSWORD.encode()), self.template_bytes)
        with open(os.path.join(self.node_dir, TEMPLATE_NAME), "rb") as f:
            self.assertEqual(f.read(), self.template_bytes)

    def test_two_installations_get_different_passwords(self):
        first, _ = ensure_rpc_password(self.node_dir)
        os.remove(self.conf)
        second, _ = ensure_rpc_password(self.node_dir)
        self.assertNotEqual(first, second)

    def test_existing_password_is_kept(self):
        first, _ = ensure_rpc_password(self.node_dir)
        self.assertEqual(ensure_rpc_password(self.node_dir), (first, False))

    def test_old_conf_with_default_password_is_migrated(self):
        with open(self.conf, "wb") as f:
            f.write(self.template_bytes)  # what v2.2.2 and older shipped as monacoin.conf
        password, changed = ensure_rpc_password(self.node_dir, lambda: False)
        self.assertTrue(changed)
        self.assertEqual(read_rpc_password(self.conf), password)

    def test_conf_is_left_alone_while_a_node_runs_with_the_default(self):
        self.assertEqual(ensure_rpc_password(self.node_dir, lambda: True), (DEFAULT_RPC_PASSWORD, False))
        self.assertEqual(read_rpc_password(self.conf), DEFAULT_RPC_PASSWORD)

    def test_no_bundled_node(self):
        with tempfile.TemporaryDirectory() as empty:
            self.assertEqual(ensure_rpc_password(empty), (None, False))


if __name__ == "__main__":
    unittest.main()
