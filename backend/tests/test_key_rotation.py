from base64 import urlsafe_b64encode
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.encryption import DEFAULT_KEY_REFERENCE, EncryptedValue, SecretBox
from app.models import Base
from app.models.access import Project, User
from app.models.api_assets import Environment, Secret
from app.models.data_sources import Credential
from app.models.governance import OrganizationGovernance, OrganizationKeyVersion
from app.models.imports import ImportRun
from app.models.organizations import Organization
from app.models.reporting import NotificationWebhook
from app.models.tasking import TestPlan as TestPlanModel
from app.models.workflows import Workflow, WorkflowExecution, WorkflowVersion
from app.services.encryption_keys import active_key_reference_for_project
from app.services.key_rotation import reencrypt_organization_ciphertexts


@pytest.mark.asyncio
async def test_reencrypts_and_rolls_back_every_organization_ciphertext_class() -> None:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    key_v1 = urlsafe_b64encode(b"0123456789abcdef0123456789abcdef").decode()
    key_v2 = urlsafe_b64encode(b"abcdef0123456789abcdef0123456789").decode()
    target_reference = "kms:organization-key-v2"
    box = SecretBox(key_v1, keyring={target_reference: key_v2})
    now = datetime.now(UTC)

    async with session_maker() as session:
        user = User(
            email="rotation@example.com",
            display_name="Rotation owner",
            password_hash="not-used",
            is_active=True,
            is_system_admin=True,
            requires_password_change=False,
        )
        session.add(user)
        await session.flush()
        organization = Organization(
            name="Rotation organization",
            slug="rotation-organization",
            description="",
            enabled=True,
            created_by_id=user.id,
        )
        session.add(organization)
        await session.flush()
        project = Project(
            organization_id=organization.id,
            name="Rotation project",
            description="",
            variables={},
            headers={},
            outbound_allowed_hosts=[],
            outbound_allowed_private_cidrs=[],
            created_by_id=user.id,
        )
        session.add(project)
        await session.flush()
        assert await active_key_reference_for_project(session, project.id) == DEFAULT_KEY_REFERENCE
        governance = OrganizationGovernance(
            organization_id=organization.id,
            quota_policies={},
            runner_policy={},
            active_key_version=2,
        )
        key_version = OrganizationKeyVersion(
            organization_id=organization.id,
            version=2,
            key_reference=target_reference,
            key_fingerprint="f" * 64,
            status="active",
            migration_status="migrated",
            previous_version=1,
            created_by_id=user.id,
            activated_at=now,
            migrated_at=now,
        )
        session.add_all([governance, key_version])
        await session.flush()
        assert await active_key_reference_for_project(session, project.id) == target_reference
        environment = Environment(
            project_id=project.id,
            name="sandbox",
            base_url="https://sandbox.example.test",
            default_service_id=None,
            variables={},
            headers={},
            created_by_id=user.id,
        )
        workflow = Workflow(
            project_id=project.id,
            folder_id=None,
            name="Rotation workflow",
            description="",
            draft_definition={},
            draft_revision=1,
            current_version=1,
            created_by_id=user.id,
        )
        session.add_all([environment, workflow])
        await session.flush()
        workflow_version = WorkflowVersion(
            workflow_id=workflow.id,
            version=1,
            definition={},
            fingerprint="f" * 64,
            created_by_id=user.id,
            published_at=now,
        )
        session.add(workflow_version)
        await session.flush()

        secret_aad = f"{project.id}:project:API_TOKEN".encode()
        secret_value = box.encrypt("secret-value", associated_data=secret_aad)
        secret = Secret(
            project_id=project.id,
            environment_id=None,
            name="API_TOKEN",
            ciphertext=secret_value.ciphertext,
            nonce=secret_value.nonce,
            created_by_id=user.id,
        )

        credential_id = uuid4()
        credential_aad = f"flowtest:credential:{project.id}:{credential_id}".encode()
        credential_value = box.encrypt("credential-value", associated_data=credential_aad)
        credential = Credential(
            id=credential_id,
            project_id=project.id,
            name="read-only database",
            kind="postgresql",
            host="db.example.test",
            port=5432,
            database_name="flowtest",
            username="reader",
            secret_provider="local",
            provider_reference=None,
            ciphertext=credential_value.ciphertext,
            nonce=credential_value.nonce,
            tls_enabled=True,
            created_by_id=user.id,
        )

        import_id = uuid4()
        import_aad = f"flowtest:import-preview:{import_id}".encode()
        import_value = box.encrypt("aW1wb3J0", associated_data=import_aad)
        import_run = ImportRun(
            id=import_id,
            project_id=project.id,
            source_kind="file",
            source_key="rotation.json",
            source_type="openapi3",
            source_name="rotation.json",
            source_url=None,
            document_url=None,
            source_sha256="a" * 64,
            added=1,
            changed=0,
            deleted=0,
            unchanged=0,
            results=[],
            status="preview",
            applied_keys=[],
            payload_ciphertext=import_value.ciphertext,
            payload_nonce=import_value.nonce,
            applied_at=None,
            created_by_id=user.id,
        )

        execution_id = uuid4()
        execution_aad = f"workflow-execution:{execution_id}:run-plan".encode()
        execution_value = box.encrypt("execution-plan", associated_data=execution_aad)
        execution = WorkflowExecution(
            id=execution_id,
            project_id=project.id,
            workflow_id=workflow.id,
            workflow_version_id=workflow_version.id,
            environment_id=environment.id,
            triggered_by_id=user.id,
            parent_execution_id=None,
            dataset_row_index=None,
            status="queued",
            main_status=None,
            cleanup_status=None,
            cleanup_report={},
            snapshot={},
            context={},
            error_code=None,
            error_message=None,
            cancel_requested_at=None,
            force_cancel_requested_at=None,
            force_cancel_reason=None,
            started_at=now,
            completed_at=None,
            run_payload_ciphertext=execution_value.ciphertext,
            run_payload_nonce=execution_value.nonce,
        )

        plan_id = uuid4()
        plan_aad = f"test-plan:{plan_id}:webhook-secret".encode()
        plan_value = box.encrypt("plan-webhook", associated_data=plan_aad)
        plan = TestPlanModel(
            id=plan_id,
            project_id=project.id,
            name="Rotation plan",
            description="",
            enabled=True,
            schedule_interval_seconds=None,
            schedule_cron=None,
            schedule_timezone="Asia/Shanghai",
            queue_priority=5,
            next_run_at=None,
            webhook_secret_ciphertext=plan_value.ciphertext,
            webhook_secret_nonce=plan_value.nonce,
            created_by_id=user.id,
        )

        webhook_id = uuid4()
        webhook_aad = f"notification-webhook:{webhook_id}".encode()
        webhook_value = box.encrypt("notification-secret", associated_data=webhook_aad)
        webhook = NotificationWebhook(
            id=webhook_id,
            project_id=project.id,
            name="Rotation webhook",
            url="https://notify.example.test",
            secret_ciphertext=webhook_value.ciphertext,
            secret_nonce=webhook_value.nonce,
            events=["workflow.completed"],
            enabled=True,
            created_by_id=user.id,
        )
        session.add_all([secret, credential, import_run, execution, plan, webhook])
        await session.commit()

        evidence = await reencrypt_organization_ciphertexts(
            session,
            organization_id=organization.id,
            target_key_reference=target_reference,
            secrets=box,
        )
        assert evidence.total == 6
        assert evidence.verified == 6
        assert set(evidence.resource_counts) == {
            "secret",
            "credential",
            "import_preview",
            "execution_plan",
            "test_plan_webhook",
            "notification_webhook",
        }
        ciphertexts = (
            secret.ciphertext,
            credential.ciphertext,
            import_run.payload_ciphertext,
            execution.run_payload_ciphertext,
            plan.webhook_secret_ciphertext,
            webhook.secret_ciphertext,
        )
        assert all(
            ciphertext is not None and box.reference(ciphertext) == target_reference
            for ciphertext in ciphertexts
        )
        assert (
            box.decrypt(
                EncryptedValue(secret.ciphertext, secret.nonce),
                associated_data=secret_aad,
            )
            == "secret-value"
        )

        rollback = await reencrypt_organization_ciphertexts(
            session,
            organization_id=organization.id,
            target_key_reference=DEFAULT_KEY_REFERENCE,
            secrets=box,
        )
        assert rollback.total == 6
        assert box.reference(secret.ciphertext) == DEFAULT_KEY_REFERENCE
        assert (
            box.decrypt(
                EncryptedValue(secret.ciphertext, secret.nonce),
                associated_data=secret_aad,
            )
            == "secret-value"
        )

    await engine.dispose()
