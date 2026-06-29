"""Tests for multi-mailbox authentication — one client per tenant."""
from unittest.mock import MagicMock, patch

from app.config.settings import MailboxConfig
from app.graph.mail_client import build_client


class TestMultiMailboxAuth:
    def test_builds_separate_clients_per_mailbox(self):
        mb1 = MailboxConfig(
            tenant_id="tenant-1",
            client_id="client-1",
            client_secret="secret-1",
            user="user1@org1.com",
        )
        mb2 = MailboxConfig(
            tenant_id="tenant-2",
            client_id="client-2",
            client_secret="secret-2",
            user="user2@org2.com",
        )

        with patch("app.graph.mail_client.ClientSecretCredential") as MockCred, \
             patch("app.graph.mail_client.GraphServiceClient") as MockClient:
            MockCred.return_value = MagicMock()
            MockClient.return_value = MagicMock()

            build_client(mb1)
            build_client(mb2)

            assert MockCred.call_count == 2
            calls = MockCred.call_args_list
            assert calls[0].kwargs["tenant_id"] == "tenant-1"
            assert calls[0].kwargs["client_id"] == "client-1"
            assert calls[1].kwargs["tenant_id"] == "tenant-2"
            assert calls[1].kwargs["client_id"] == "client-2"

    def test_client_secret_passed_correctly(self):
        mb = MailboxConfig(
            tenant_id="t",
            client_id="c",
            client_secret="my-super-secret",
            user="u@u.com",
        )
        with patch("app.graph.mail_client.ClientSecretCredential") as MockCred, \
             patch("app.graph.mail_client.GraphServiceClient"):
            MockCred.return_value = MagicMock()
            build_client(mb)
            assert MockCred.call_args.kwargs["client_secret"] == "my-super-secret"

    def test_different_tenants_produce_different_credentials(self):
        configs = [
            MailboxConfig("t1", "c1", "s1", "u1@a.com"),
            MailboxConfig("t2", "c2", "s2", "u2@b.com"),
        ]
        with patch("app.graph.mail_client.ClientSecretCredential") as MockCred, \
             patch("app.graph.mail_client.GraphServiceClient"):
            MockCred.return_value = MagicMock()
            for cfg in configs:
                build_client(cfg)
            tenant_ids = [call.kwargs["tenant_id"] for call in MockCred.call_args_list]
            assert tenant_ids == ["t1", "t2"]
