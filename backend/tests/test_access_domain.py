from uuid import uuid4

import pytest

from app.domain.access import FolderMoveError, ProjectRole, validate_folder_parent


def test_project_roles_have_fixed_capabilities() -> None:
    assert ProjectRole.OWNER.can_edit
    assert ProjectRole.OWNER.can_manage_members
    assert ProjectRole.EDITOR.can_edit
    assert not ProjectRole.EDITOR.can_manage_members
    assert not ProjectRole.VIEWER.can_edit


def test_folder_cannot_move_to_itself_or_descendant() -> None:
    folder_id = uuid4()
    descendant_id = uuid4()

    with pytest.raises(FolderMoveError, match="自身"):
        validate_folder_parent(
            folder_id=folder_id,
            new_parent_id=folder_id,
            ancestor_ids={descendant_id},
        )
    with pytest.raises(FolderMoveError, match="子目录"):
        validate_folder_parent(
            folder_id=folder_id,
            new_parent_id=descendant_id,
            ancestor_ids={descendant_id},
        )


def test_folder_can_move_to_root_or_unrelated_folder() -> None:
    folder_id = uuid4()
    validate_folder_parent(folder_id=folder_id, new_parent_id=None, ancestor_ids=set())
    validate_folder_parent(folder_id=folder_id, new_parent_id=uuid4(), ancestor_ids=set())
