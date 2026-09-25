"""Skip boot “No SpotPass data found.” when GetNsDataNewFlag is 0."""

from __future__ import annotations

from conftest import SRC, load_module

sp = load_module("patch_spotpass_skip", SRC / "patch_spotpass_skip.py")


def _blob(moveq: bytes, jt: bytes | None = None, nops: bool | None = None) -> bytearray:
    data = bytearray(max(sp.DIALOG_SITES[-1], sp.FUN_APPLY_WAIT) + 32)
    if jt is None:
        jt = sp.PATCHED_JT0 if moveq == sp.PATCHED_MOVEQ else sp.VANILLA_JT0
    if nops is None:
        nops = moveq == sp.PATCHED_MOVEQ
    data[sp.ADDR_JT0 : sp.ADDR_JT0 + 4] = jt
    data[sp.ADDR_CMP : sp.ADDR_CMP + 4] = sp.VANILLA_CMP
    data[sp.ADDR_MOVEQ : sp.ADDR_MOVEQ + 4] = moveq
    data[sp.ADDR_MOVEQ + 4 : sp.ADDR_MOVEQ + 8] = sp.VANILLA_STRB
    for site in sp.DIALOG_SITES:
        data[site : site + 4] = sp.NOP if nops else sp._bl_to_dialog(site)
    popup = nops
    data[sp.ADDR_NODATA_BL : sp.ADDR_NODATA_BL + 4] = (
        sp.NOP if popup else sp._bl_to_syspopup()
    )
    data[sp.ADDR_NODATA2_BEQ : sp.ADDR_NODATA2_BEQ + 4] = (
        sp.PATCHED_NODATA2_BEQ if popup else sp.VANILLA_NODATA2_BEQ
    )
    for site in sp.BIND_SITES:
        data[site : site + 4] = sp.NOP if nops else sp._bl_to_bind(site)
    for site in sp.SHOW_SITES:
        data[site : site + 4] = sp.NOP if nops else sp._bl_to_show(site)
    data[sp.ADDR_UI_JT0 : sp.ADDR_UI_JT0 + 4] = sp.VANILLA_UI_JT0
    data[sp.ADDR_STATE0 : sp.ADDR_STATE0 + sp.STATE0_LEN] = (
        sp.PATCHED_STATE0 if nops else sp.VANILLA_STATE0
    )
    data[sp.ADDR_OPEN_WARN : sp.ADDR_OPEN_WARN + 4] = (
        sp.PATCHED_OPEN_WARN if nops else sp.VANILLA_OPEN_WARN
    )
    data[sp.ADDR_STATE4_SHOW : sp.ADDR_STATE4_SHOW + 4] = (
        sp.PATCHED_STATE4_SHOW if nops else sp.VANILLA_STATE4_SHOW
    )
    data[sp.ADDR_EBE_START : sp.ADDR_EBE_START + 4] = (
        sp.NOP if nops else sp.VANILLA_EBE_START
    )
    data[sp.ADDR_EBE_ST1 : sp.ADDR_EBE_ST1 + 4] = (
        sp.PATCHED_EBE_STATE if nops else sp.VANILLA_EBE_ST1
    )
    data[sp.ADDR_EBE_ST4 : sp.ADDR_EBE_ST4 + 4] = (
        sp.PATCHED_EBE_STATE if nops else sp.VANILLA_EBE_ST4
    )
    data[sp.ADDR_EBE_ST3 : sp.ADDR_EBE_ST3 + 4] = (
        sp.PATCHED_EBE_STATE if nops else sp.VANILLA_EBE_ST3
    )
    data[sp.ADDR_TITLE_FAIL_BEQ : sp.ADDR_TITLE_FAIL_BEQ + 4] = (
        sp.PATCHED_TITLE_FAIL_BEQ if nops else sp.VANILLA_TITLE_FAIL_BEQ
    )
    data[sp.ADDR_TITLE_FAIL_STORES : sp.ADDR_TITLE_FAIL_STORES + 4] = (
        sp.PATCHED_TITLE_FAIL_STORES if nops else sp.VANILLA_TITLE_FAIL_STORES
    )
    data[sp.ADDR_TITLE_D201 : sp.ADDR_TITLE_D201 + 4] = (
        sp.PATCHED_TITLE_D201 if nops else sp.VANILLA_TITLE_D201
    )
    data[sp.ADDR_EE9_JT6 : sp.ADDR_EE9_JT6 + 4] = (
        sp.PATCHED_EE9_JT6 if nops else sp.VANILLA_EE9_JT6
    )
    data[sp.ADDR_EE9_ST6 : sp.ADDR_EE9_ST6 + 4] = (
        sp.PATCHED_EE9_ST6 if nops else sp.VANILLA_EE9_ST6
    )
    for site in sp.WAIT_SITES:
        data[site : site + sp.WAIT_LEN] = (
            sp._wait_patched_bytes(site) if nops else sp._wait_vanilla_bytes(site)
        )
    for site in sp.SHOW_APPLY_SITES:
        data[site : site + 4] = (
            sp.NOP if nops else sp._bl_to_apply_show(site)
        )
    for site in sp.ADDR_14ED_TO_APPLY:
        data[site : site + 4] = (
            sp.patched_14ed_mov(site) if nops else sp.VANILLA_14ED_TO_APPLY[site]
        )
    for slot in sp._14ED_APPLY_SLOTS:
        off = sp._14ed_jt_off(slot)
        data[off : off + 4] = (
            sp.PATCHED_14ED_JT_APPLY
            if nops
            else sp._14ed_jt_va(sp.VANILLA_14ED_JT_APPLY_FILE[slot])
        )
    for site in sp.ADDR_14ED_WAIT_STAY:
        data[site : site + 4] = (
            sp.NOP if nops else sp.VANILLA_14ED_WAIT_STAY[site]
        )
    data[sp.ADDR_14ED_ERROR : sp.ADDR_14ED_ERROR + 4] = (
        sp.PATCHED_14ED_ERROR if nops else sp.VANILLA_14ED_ERROR
    )
    data[sp.ADDR_14ED_ST1_DATA : sp.ADDR_14ED_ST1_DATA + 4] = (
        sp.PATCHED_14ED_ST1_DATA if nops else sp.VANILLA_14ED_ST1_DATA
    )
    data[sp.ADDR_14B890_MULTIWIN : sp.ADDR_14B890_MULTIWIN + 4] = (
        sp.NOP if nops else sp.VANILLA_14B890_MULTIWIN
    )
    data[sp.ADDR_14E648_ERROR : sp.ADDR_14E648_ERROR + 4] = (
        sp.PATCHED_14E648_ERROR if nops else sp.VANILLA_14E648_ERROR
    )
    data[sp.ADDR_14ED_ST3_MULTIWIN : sp.ADDR_14ED_ST3_MULTIWIN + 4] = (
        sp.NOP if nops else sp.VANILLA_14ED_ST3_MULTIWIN
    )
    data[sp.ADDR_COMMOPT_D201 : sp.ADDR_COMMOPT_D201 + 4] = (
        sp.PATCHED_COMMOPT_D201 if nops else sp.VANILLA_COMMOPT_D201
    )
    data[sp.ADDR_COMMOPT_D201_FAIL : sp.ADDR_COMMOPT_D201_FAIL + 4] = (
        sp.PATCHED_COMMOPT_D201_FAIL if nops else sp.VANILLA_COMMOPT_D201_FAIL
    )
    data[sp.ADDR_TITLE_STUB : sp.ADDR_TITLE_STUB + sp.TITLE_STUB_LEN] = (
        sp.PATCHED_TITLE_STUB if nops else sp.VANILLA_TITLE_STUB
    )
    data[sp.ADDR_TITLE_ST6_SHOW : sp.ADDR_TITLE_ST6_SHOW + 4] = (
        sp.NOP if nops else sp.VANILLA_TITLE_ST6_SHOW
    )
    data[sp.ADDR_TITLE_ST1_SHOW : sp.ADDR_TITLE_ST1_SHOW + 4] = sp.VANILLA_TITLE_ST1_SHOW
    data[sp.ADDR_TITLE_ST2_STAY : sp.ADDR_TITLE_ST2_STAY + 4] = (
        sp.NOP if nops else sp.VANILLA_TITLE_ST2_STAY
    )
    data[sp.ADDR_TITLE_ST8_HEAD : sp.ADDR_TITLE_ST8_HEAD + 4] = sp.VANILLA_TITLE_ST8_HEAD
    data[sp.ADDR_TITLE_ST8_SKIP : sp.ADDR_TITLE_ST8_SKIP + 4] = (
        sp.PATCHED_TITLE_ST8_SKIP if nops else sp.VANILLA_TITLE_ST8_SKIP
    )
    data[sp.ADDR_TITLE_ST8_GATE : sp.ADDR_TITLE_ST8_GATE + 4] = sp.VANILLA_TITLE_ST8_GATE
    data[sp.ADDR_TITLE_ST8_POLL : sp.ADDR_TITLE_ST8_POLL + 4] = sp.VANILLA_TITLE_ST8_POLL
    data[sp.ADDR_TITLE_ST8_STAY : sp.ADDR_TITLE_ST8_STAY + 4] = sp.VANILLA_TITLE_ST8_STAY
    data[sp.ADDR_TITLE_ST8_READY : sp.ADDR_TITLE_ST8_READY + 4] = (
        sp.NOP if nops else sp.VANILLA_TITLE_ST8_READY
    )
    data[sp.ADDR_TITLE_ST8_LAYOUT : sp.ADDR_TITLE_ST8_LAYOUT + 4] = sp.VANILLA_TITLE_ST8_LAYOUT
    data[sp.ADDR_TITLE_ST18_STAY : sp.ADDR_TITLE_ST18_STAY + 4] = sp.VANILLA_TITLE_ST18_STAY
    data[sp.ADDR_TITLE_ST8_TAIL : sp.ADDR_TITLE_ST8_TAIL + 4] = sp.VANILLA_TITLE_ST8_TAIL
    data[sp.ADDR_TITLE_ST8_TAIL2 : sp.ADDR_TITLE_ST8_TAIL2 + 4] = sp.VANILLA_TITLE_ST8_TAIL2
    data[sp.ADDR_TITLE_HIDE_CAVE : sp.ADDR_TITLE_HIDE_CAVE + sp.HIDE_CAVE_LEN] = (
        sp.PATCHED_TITLE_HIDE_CAVE if nops else sp.VANILLA_TITLE_HIDE_CAVE
    )
    data[sp.ADDR_TITLE_CMP_MAX : sp.ADDR_TITLE_CMP_MAX + 4] = sp.VANILLA_TITLE_CMP_MAX
    data[sp.ADDR_TITLE_OOR : sp.ADDR_TITLE_OOR + 4] = sp.VANILLA_TITLE_OOR
    data[sp.ADDR_TYPE2_1E5 : sp.ADDR_TYPE2_1E5 + 4] = (
        sp.PATCHED_TYPE2_1E5 if nops else sp.VANILLA_TYPE2_1E5
    )
    data[sp.ADDR_TITLE_MSGID : sp.ADDR_TITLE_MSGID + 4] = sp.VANILLA_TITLE_MSGID
    for slot in sp.TITLE_JT_SLOTS:
        off = sp._title_jt_off(slot)
        data[off : off + 4] = (
            sp.PATCHED_TITLE_JT_VA if nops else sp.VANILLA_TITLE_JT[slot]
        )
    for site in sp.SHOW_APPLY_TAILS:
        data[site : site + 4] = (
            sp.PATCHED_BX_LR if nops else sp._b_to_apply_show(site)
        )
    data[sp.FUN_APPLY_SHOW : sp.FUN_APPLY_SHOW + 4] = sp.VANILLA_SHOW_FN
    data[sp.FUN_APPLY_WAIT_OV : sp.FUN_APPLY_WAIT_OV + 8] = sp.VANILLA_WAIT_OV_FN
    data[sp.FUN_APPLY_WAIT : sp.FUN_APPLY_WAIT + sp.WAIT_APPLY_HEAD_LEN] = (
        sp.VANILLA_WAIT_APPLY_HEAD
    )
    return data


def test_spotpass_skip_rewrites_error_imm():
    data = _blob(sp.VANILLA_MOVEQ)
    assert sp.is_vanilla(data)
    assert not sp.is_patched(data)
    assert sp.apply_patch(data) is True
    assert data[sp.ADDR_MOVEQ : sp.ADDR_MOVEQ + 4] == sp.PATCHED_MOVEQ
    assert data[sp.ADDR_JT0 : sp.ADDR_JT0 + 4] == sp.PATCHED_JT0
    assert data[sp.DIALOG_SITES[0] : sp.DIALOG_SITES[0] + 4] == sp.NOP
    assert data[sp.DIALOG_SITES[-1] : sp.DIALOG_SITES[-1] + 4] == sp.NOP
    assert data[sp.ADDR_NODATA_BL : sp.ADDR_NODATA_BL + 4] == sp.NOP
    assert data[sp.ADDR_NODATA2_BEQ : sp.ADDR_NODATA2_BEQ + 4] == sp.PATCHED_NODATA2_BEQ
    assert data[sp.BIND_SITES[0] : sp.BIND_SITES[0] + 4] == sp.NOP
    assert data[sp.SHOW_SITES[0] : sp.SHOW_SITES[0] + 4] == sp.NOP
    assert data[sp.ADDR_UI_JT0 : sp.ADDR_UI_JT0 + 4] == sp.VANILLA_UI_JT0
    assert data[sp.ADDR_STATE0 : sp.ADDR_STATE0 + sp.STATE0_LEN] == sp.PATCHED_STATE0
    assert data[sp.ADDR_OPEN_WARN : sp.ADDR_OPEN_WARN + 4] == sp.PATCHED_OPEN_WARN
    assert data[sp.ADDR_STATE4_SHOW : sp.ADDR_STATE4_SHOW + 4] == sp.PATCHED_STATE4_SHOW
    assert data[sp.ADDR_EBE_START : sp.ADDR_EBE_START + 4] == sp.NOP
    assert data[sp.ADDR_EBE_ST1 : sp.ADDR_EBE_ST1 + 4] == sp.PATCHED_EBE_STATE
    assert data[sp.ADDR_EBE_ST4 : sp.ADDR_EBE_ST4 + 4] == sp.PATCHED_EBE_STATE
    assert data[sp.ADDR_EBE_ST3 : sp.ADDR_EBE_ST3 + 4] == sp.PATCHED_EBE_STATE
    assert data[sp.ADDR_TITLE_FAIL_BEQ : sp.ADDR_TITLE_FAIL_BEQ + 4] == sp.PATCHED_TITLE_FAIL_BEQ
    assert data[sp.ADDR_TITLE_FAIL_STORES : sp.ADDR_TITLE_FAIL_STORES + 4] == sp.PATCHED_TITLE_FAIL_STORES
    assert data[sp.ADDR_TITLE_D201 : sp.ADDR_TITLE_D201 + 4] == sp.PATCHED_TITLE_D201
    assert data[sp.ADDR_EE9_JT6 : sp.ADDR_EE9_JT6 + 4] == sp.PATCHED_EE9_JT6
    assert data[sp.ADDR_EE9_ST6 : sp.ADDR_EE9_ST6 + 4] == sp.PATCHED_EE9_ST6
    assert data[sp.WAIT_SITES[0] : sp.WAIT_SITES[0] + sp.WAIT_LEN] == sp._wait_patched_bytes(
        sp.WAIT_SITES[0]
    )
    assert data[sp.SHOW_APPLY_SITES[0] : sp.SHOW_APPLY_SITES[0] + 4] == sp.NOP
    assert data[sp.ADDR_14ED_TO_APPLY[0] : sp.ADDR_14ED_TO_APPLY[0] + 4] == (
        sp.PATCHED_14ED_NAMECARD
    )
    assert data[sp._14ed_jt_off(24) : sp._14ed_jt_off(24) + 4] == sp.PATCHED_14ED_JT_APPLY
    assert data[sp.ADDR_14ED_WAIT_STAY[0] : sp.ADDR_14ED_WAIT_STAY[0] + 4] == sp.NOP
    assert data[sp.ADDR_14ED_ERROR : sp.ADDR_14ED_ERROR + 4] == sp.PATCHED_14ED_ERROR
    assert data[sp.ADDR_14ED_ST1_DATA : sp.ADDR_14ED_ST1_DATA + 4] == sp.PATCHED_14ED_ST1_DATA
    assert data[sp.ADDR_14B890_MULTIWIN : sp.ADDR_14B890_MULTIWIN + 4] == sp.NOP
    assert data[sp.ADDR_14E648_ERROR : sp.ADDR_14E648_ERROR + 4] == sp.PATCHED_14E648_ERROR
    assert data[sp.ADDR_14ED_ST3_MULTIWIN : sp.ADDR_14ED_ST3_MULTIWIN + 4] == sp.NOP
    assert data[sp.ADDR_COMMOPT_D201 : sp.ADDR_COMMOPT_D201 + 4] == sp.PATCHED_COMMOPT_D201
    assert data[sp.ADDR_COMMOPT_D201_FAIL : sp.ADDR_COMMOPT_D201_FAIL + 4] == (
        sp.PATCHED_COMMOPT_D201_FAIL
    )
    assert data[sp.ADDR_TITLE_ST1_SHOW : sp.ADDR_TITLE_ST1_SHOW + 4] == sp.VANILLA_TITLE_ST1_SHOW
    assert data[sp.FUN_APPLY_SHOW : sp.FUN_APPLY_SHOW + 4] == sp.VANILLA_SHOW_FN
    assert data[sp.ADDR_TITLE_STUB : sp.ADDR_TITLE_STUB + sp.TITLE_STUB_LEN] == sp.PATCHED_TITLE_STUB
    assert data[sp.SHOW_APPLY_TAILS[0] : sp.SHOW_APPLY_TAILS[0] + 4] == sp.PATCHED_BX_LR
    assert data[sp.ADDR_14ED_ST1_DATA : sp.ADDR_14ED_ST1_DATA + 4] == sp.VANILLA_14ED_ST1_DATA
    assert sp.is_patched(data)
    assert sp.apply_patch(data) is False


def test_spotpass_skip_restores_namecard_setup():
    data = _blob(sp.PATCHED_MOVEQ)
    data[sp.ADDR_14ED_ST1_DATA : sp.ADDR_14ED_ST1_DATA + 4] = sp.OLD_14ED_ST1_SKIP
    assert not sp.is_patched(data)
    assert sp.apply_patch(data) is True
    assert data[sp.ADDR_14ED_ST1_DATA : sp.ADDR_14ED_ST1_DATA + 4] == sp.VANILLA_14ED_ST1_DATA
    assert sp.is_patched(data)


def test_spotpass_skip_upgrades_old_manager_only_patch():
    data = _blob(sp.PATCHED_MOVEQ)
    data[sp.ADDR_NODATA_BL : sp.ADDR_NODATA_BL + 4] = sp._bl_to_syspopup()
    data[sp.ADDR_NODATA2_BEQ : sp.ADDR_NODATA2_BEQ + 4] = sp.VANILLA_NODATA2_BEQ
    for site in sp.BIND_SITES:
        data[site : site + 4] = sp._bl_to_bind(site)
    for site in sp.SHOW_SITES:
        data[site : site + 4] = sp._bl_to_show(site)
    data[sp.ADDR_UI_JT0 : sp.ADDR_UI_JT0 + 4] = sp.OLD_DISMISS_UI_JT0
    data[sp.ADDR_STATE0 : sp.ADDR_STATE0 + sp.STATE0_LEN] = sp.VANILLA_STATE0
    assert not sp.is_vanilla(data)
    assert not sp.is_patched(data)
    assert sp.apply_patch(data) is True
    assert data[sp.ADDR_NODATA_BL : sp.ADDR_NODATA_BL + 4] == sp.NOP
    assert data[sp.BIND_SITES[0] : sp.BIND_SITES[0] + 4] == sp.NOP
    assert data[sp.SHOW_SITES[0] : sp.SHOW_SITES[0] + 4] == sp.NOP
    assert sp.is_patched(data)


def test_spotpass_skip_upgrades_popup_without_pane_binds():
    data = _blob(sp.PATCHED_MOVEQ)
    for site in sp.BIND_SITES:
        data[site : site + 4] = sp._bl_to_bind(site)
    for site in sp.SHOW_SITES:
        data[site : site + 4] = sp._bl_to_show(site)
    assert not sp.is_patched(data)
    assert sp.apply_patch(data) is True
    assert data[sp.BIND_SITES[-1] : sp.BIND_SITES[-1] + 4] == sp.NOP
    assert data[sp.SHOW_SITES[-1] : sp.SHOW_SITES[-1] + 4] == sp.NOP
    assert sp.is_patched(data)


def test_spotpass_skip_upgrades_binds_without_show():
    data = _blob(sp.PATCHED_MOVEQ)
    for site in sp.SHOW_SITES:
        data[site : site + 4] = sp._bl_to_show(site)
    data[sp.ADDR_UI_JT0 : sp.ADDR_UI_JT0 + 4] = sp.OLD_DISMISS_UI_JT0
    data[sp.ADDR_STATE0 : sp.ADDR_STATE0 + sp.STATE0_LEN] = sp.VANILLA_STATE0
    assert not sp.is_patched(data)
    assert sp.apply_patch(data) is True
    assert data[sp.SHOW_SITES[0] : sp.SHOW_SITES[0] + 4] == sp.NOP
    assert data[sp.ADDR_STATE0 : sp.ADDR_STATE0 + sp.STATE0_LEN] == sp.PATCHED_STATE0
    assert sp.is_patched(data)


def test_spotpass_skip_upgrades_show_without_ui_jt():
    data = _blob(sp.PATCHED_MOVEQ)
    data[sp.ADDR_STATE0 : sp.ADDR_STATE0 + sp.STATE0_LEN] = sp.VANILLA_STATE0
    data[sp.ADDR_UI_JT0 : sp.ADDR_UI_JT0 + 4] = sp.OLD_DISMISS_UI_JT0
    assert not sp.is_patched(data)
    assert sp.apply_patch(data) is True
    assert data[sp.ADDR_STATE0 : sp.ADDR_STATE0 + sp.STATE0_LEN] == sp.PATCHED_STATE0
    assert data[sp.ADDR_UI_JT0 : sp.ADDR_UI_JT0 + 4] == sp.VANILLA_UI_JT0
    assert sp.is_patched(data)


def test_spotpass_skip_revert_restores_vanilla():
    data = _blob(sp.PATCHED_MOVEQ)
    assert sp.revert_patch(data) is True
    assert sp.is_vanilla(data)
    assert data[sp.ADDR_JT0 : sp.ADDR_JT0 + 4] == sp.VANILLA_JT0
    assert data[sp.DIALOG_SITES[0] : sp.DIALOG_SITES[0] + 4] == sp._bl_to_dialog(
        sp.DIALOG_SITES[0]
    )
    assert data[sp.ADDR_NODATA_BL : sp.ADDR_NODATA_BL + 4] == sp._bl_to_syspopup()
    assert data[sp.ADDR_NODATA2_BEQ : sp.ADDR_NODATA2_BEQ + 4] == sp.VANILLA_NODATA2_BEQ
    assert data[sp.BIND_SITES[0] : sp.BIND_SITES[0] + 4] == sp._bl_to_bind(
        sp.BIND_SITES[0]
    )
    assert data[sp.SHOW_SITES[0] : sp.SHOW_SITES[0] + 4] == sp._bl_to_show(
        sp.SHOW_SITES[0]
    )
    assert data[sp.ADDR_UI_JT0 : sp.ADDR_UI_JT0 + 4] == sp.VANILLA_UI_JT0
    assert data[sp.ADDR_STATE0 : sp.ADDR_STATE0 + sp.STATE0_LEN] == sp.VANILLA_STATE0
    assert data[sp.ADDR_OPEN_WARN : sp.ADDR_OPEN_WARN + 4] == sp.VANILLA_OPEN_WARN
    assert data[sp.ADDR_STATE4_SHOW : sp.ADDR_STATE4_SHOW + 4] == sp.VANILLA_STATE4_SHOW
    assert data[sp.ADDR_EBE_START : sp.ADDR_EBE_START + 4] == sp.VANILLA_EBE_START
    assert data[sp.ADDR_TITLE_D201 : sp.ADDR_TITLE_D201 + 4] == sp.VANILLA_TITLE_D201
    assert data[sp.ADDR_EE9_JT6 : sp.ADDR_EE9_JT6 + 4] == sp.VANILLA_EE9_JT6
    assert data[sp.WAIT_SITES[0] : sp.WAIT_SITES[0] + sp.WAIT_LEN] == sp._wait_vanilla_bytes(
        sp.WAIT_SITES[0]
    )
    assert data[sp.ADDR_TITLE_STUB : sp.ADDR_TITLE_STUB + sp.TITLE_STUB_LEN] == sp.VANILLA_TITLE_STUB
    assert sp.revert_patch(data) is False


def test_spotpass_skip_upgrades_hide_without_ui2():
    data = _blob(sp.PATCHED_MOVEQ)
    data[sp.ADDR_STATE4_SHOW : sp.ADDR_STATE4_SHOW + 4] = sp.VANILLA_STATE4_SHOW
    data[sp.ADDR_EBE_START : sp.ADDR_EBE_START + 4] = sp.VANILLA_EBE_START
    data[sp.ADDR_EBE_ST1 : sp.ADDR_EBE_ST1 + 4] = sp.VANILLA_EBE_ST1
    data[sp.ADDR_EBE_ST4 : sp.ADDR_EBE_ST4 + 4] = sp.VANILLA_EBE_ST4
    data[sp.ADDR_EBE_ST3 : sp.ADDR_EBE_ST3 + 4] = sp.VANILLA_EBE_ST3
    data[sp.ADDR_TITLE_FAIL_BEQ : sp.ADDR_TITLE_FAIL_BEQ + 4] = sp.VANILLA_TITLE_FAIL_BEQ
    data[sp.ADDR_TITLE_FAIL_STORES : sp.ADDR_TITLE_FAIL_STORES + 4] = sp.VANILLA_TITLE_FAIL_STORES
    data[sp.ADDR_TITLE_D201 : sp.ADDR_TITLE_D201 + 4] = sp.VANILLA_TITLE_D201
    data[sp.ADDR_EE9_JT6 : sp.ADDR_EE9_JT6 + 4] = sp.VANILLA_EE9_JT6
    data[sp.ADDR_EE9_ST6 : sp.ADDR_EE9_ST6 + 4] = sp.VANILLA_EE9_ST6
    for site in sp.WAIT_SITES:
        data[site : site + sp.WAIT_LEN] = sp._wait_vanilla_bytes(site)
    for site in sp.SHOW_APPLY_SITES:
        data[site : site + 4] = sp._bl_to_apply_show(site)
    for site in sp.ADDR_14ED_TO_APPLY:
        data[site : site + 4] = sp.VANILLA_14ED_TO_APPLY[site]
    for slot in sp._14ED_APPLY_SLOTS:
        off = sp._14ed_jt_off(slot)
        data[off : off + 4] = sp._14ed_jt_va(sp.VANILLA_14ED_JT_APPLY_FILE[slot])
    for site in sp.ADDR_14ED_WAIT_STAY:
        data[site : site + 4] = sp.VANILLA_14ED_WAIT_STAY[site]
    data[sp.ADDR_14ED_ERROR : sp.ADDR_14ED_ERROR + 4] = sp.VANILLA_14ED_ERROR
    data[sp.ADDR_14ED_ST1_DATA : sp.ADDR_14ED_ST1_DATA + 4] = sp.VANILLA_14ED_ST1_DATA
    data[sp.ADDR_14B890_MULTIWIN : sp.ADDR_14B890_MULTIWIN + 4] = (
        sp.VANILLA_14B890_MULTIWIN
    )
    data[sp.ADDR_14E648_ERROR : sp.ADDR_14E648_ERROR + 4] = sp.VANILLA_14E648_ERROR
    data[sp.ADDR_14ED_ST3_MULTIWIN : sp.ADDR_14ED_ST3_MULTIWIN + 4] = (
        sp.VANILLA_14ED_ST3_MULTIWIN
    )
    data[sp.ADDR_COMMOPT_D201 : sp.ADDR_COMMOPT_D201 + 4] = sp.VANILLA_COMMOPT_D201
    data[sp.ADDR_COMMOPT_D201_FAIL : sp.ADDR_COMMOPT_D201_FAIL + 4] = (
        sp.VANILLA_COMMOPT_D201_FAIL
    )
    data[sp.ADDR_TITLE_STUB : sp.ADDR_TITLE_STUB + sp.TITLE_STUB_LEN] = sp.VANILLA_TITLE_STUB
    data[sp.ADDR_TITLE_ST6_SHOW : sp.ADDR_TITLE_ST6_SHOW + 4] = sp.VANILLA_TITLE_ST6_SHOW
    data[sp.ADDR_TITLE_ST1_SHOW : sp.ADDR_TITLE_ST1_SHOW + 4] = sp.VANILLA_TITLE_ST1_SHOW
    data[sp.ADDR_TITLE_ST2_STAY : sp.ADDR_TITLE_ST2_STAY + 4] = sp.VANILLA_TITLE_ST2_STAY
    data[sp.ADDR_TITLE_ST8_HEAD : sp.ADDR_TITLE_ST8_HEAD + 4] = sp.VANILLA_TITLE_ST8_HEAD
    data[sp.ADDR_TITLE_ST8_SKIP : sp.ADDR_TITLE_ST8_SKIP + 4] = sp.VANILLA_TITLE_ST8_SKIP
    data[sp.ADDR_TITLE_ST8_GATE : sp.ADDR_TITLE_ST8_GATE + 4] = sp.VANILLA_TITLE_ST8_GATE
    data[sp.ADDR_TITLE_ST8_POLL : sp.ADDR_TITLE_ST8_POLL + 4] = sp.VANILLA_TITLE_ST8_POLL
    data[sp.ADDR_TITLE_ST8_STAY : sp.ADDR_TITLE_ST8_STAY + 4] = sp.VANILLA_TITLE_ST8_STAY
    data[sp.ADDR_TITLE_ST8_READY : sp.ADDR_TITLE_ST8_READY + 4] = sp.VANILLA_TITLE_ST8_READY
    data[sp.ADDR_TITLE_ST8_LAYOUT : sp.ADDR_TITLE_ST8_LAYOUT + 4] = sp.VANILLA_TITLE_ST8_LAYOUT
    data[sp.ADDR_TITLE_ST18_STAY : sp.ADDR_TITLE_ST18_STAY + 4] = sp.VANILLA_TITLE_ST18_STAY
    data[sp.ADDR_TITLE_ST8_TAIL : sp.ADDR_TITLE_ST8_TAIL + 4] = sp.VANILLA_TITLE_ST8_TAIL
    data[sp.ADDR_TITLE_ST8_TAIL2 : sp.ADDR_TITLE_ST8_TAIL2 + 4] = sp.VANILLA_TITLE_ST8_TAIL2
    data[sp.ADDR_TITLE_HIDE_CAVE : sp.ADDR_TITLE_HIDE_CAVE + sp.HIDE_CAVE_LEN] = (
        sp.VANILLA_TITLE_HIDE_CAVE
    )
    data[sp.ADDR_TITLE_CMP_MAX : sp.ADDR_TITLE_CMP_MAX + 4] = sp.VANILLA_TITLE_CMP_MAX
    data[sp.ADDR_TITLE_OOR : sp.ADDR_TITLE_OOR + 4] = sp.VANILLA_TITLE_OOR
    data[sp.ADDR_TYPE2_1E5 : sp.ADDR_TYPE2_1E5 + 4] = sp.VANILLA_TYPE2_1E5
    data[sp.ADDR_TITLE_MSGID : sp.ADDR_TITLE_MSGID + 4] = sp.VANILLA_TITLE_MSGID
    for slot in sp.TITLE_JT_SLOTS:
        off = sp._title_jt_off(slot)
        data[off : off + 4] = sp.VANILLA_TITLE_JT[slot]
    for site in sp.SHOW_APPLY_TAILS:
        data[site : site + 4] = sp._b_to_apply_show(site)
    data[sp.FUN_APPLY_SHOW : sp.FUN_APPLY_SHOW + 4] = sp.VANILLA_SHOW_FN
    data[sp.FUN_APPLY_WAIT_OV : sp.FUN_APPLY_WAIT_OV + 8] = sp.VANILLA_WAIT_OV_FN
    data[sp.FUN_APPLY_WAIT : sp.FUN_APPLY_WAIT + sp.WAIT_APPLY_HEAD_LEN] = (
        sp.VANILLA_WAIT_APPLY_HEAD
    )
    assert not sp.is_patched(data)
    assert sp.apply_patch(data) is True
    assert data[sp.ADDR_STATE4_SHOW : sp.ADDR_STATE4_SHOW + 4] == sp.PATCHED_STATE4_SHOW
    assert data[sp.ADDR_EBE_START : sp.ADDR_EBE_START + 4] == sp.NOP
    assert data[sp.ADDR_EBE_ST1 : sp.ADDR_EBE_ST1 + 4] == sp.PATCHED_EBE_STATE
    assert data[sp.ADDR_EBE_ST4 : sp.ADDR_EBE_ST4 + 4] == sp.PATCHED_EBE_STATE
    assert data[sp.ADDR_TITLE_D201 : sp.ADDR_TITLE_D201 + 4] == sp.PATCHED_TITLE_D201
    assert data[sp.ADDR_EE9_JT6 : sp.ADDR_EE9_JT6 + 4] == sp.PATCHED_EE9_JT6
    assert data[sp.ADDR_EE9_ST6 : sp.ADDR_EE9_ST6 + 4] == sp.PATCHED_EE9_ST6
    assert data[sp.WAIT_SITES[0] : sp.WAIT_SITES[0] + sp.WAIT_LEN] == sp._wait_patched_bytes(
        sp.WAIT_SITES[0]
    )
    assert data[sp.SHOW_APPLY_SITES[-1] : sp.SHOW_APPLY_SITES[-1] + 4] == sp.NOP
    assert data[sp.ADDR_14ED_TO_APPLY[0] : sp.ADDR_14ED_TO_APPLY[0] + 4] == (
        sp.PATCHED_14ED_NAMECARD
    )
    assert data[sp._14ed_jt_off(24) : sp._14ed_jt_off(24) + 4] == sp.PATCHED_14ED_JT_APPLY
    assert data[sp._14ed_jt_off(31) : sp._14ed_jt_off(31) + 4] == sp.PATCHED_14ED_JT_APPLY
    assert data[sp.ADDR_14ED_WAIT_STAY[-1] : sp.ADDR_14ED_WAIT_STAY[-1] + 4] == sp.NOP
    assert data[sp.ADDR_14ED_ERROR : sp.ADDR_14ED_ERROR + 4] == sp.PATCHED_14ED_ERROR
    assert data[sp.ADDR_14ED_ST1_DATA : sp.ADDR_14ED_ST1_DATA + 4] == sp.PATCHED_14ED_ST1_DATA
    assert data[sp.ADDR_14B890_MULTIWIN : sp.ADDR_14B890_MULTIWIN + 4] == sp.NOP
    assert data[sp.ADDR_14E648_ERROR : sp.ADDR_14E648_ERROR + 4] == sp.PATCHED_14E648_ERROR
    assert data[sp.ADDR_14ED_ST3_MULTIWIN : sp.ADDR_14ED_ST3_MULTIWIN + 4] == sp.NOP
    assert data[sp.ADDR_COMMOPT_D201 : sp.ADDR_COMMOPT_D201 + 4] == sp.PATCHED_COMMOPT_D201
    assert data[sp.ADDR_COMMOPT_D201_FAIL : sp.ADDR_COMMOPT_D201_FAIL + 4] == (
        sp.PATCHED_COMMOPT_D201_FAIL
    )
    assert data[sp.ADDR_TITLE_ST1_SHOW : sp.ADDR_TITLE_ST1_SHOW + 4] == sp.VANILLA_TITLE_ST1_SHOW
    assert data[sp.FUN_APPLY_SHOW : sp.FUN_APPLY_SHOW + 4] == sp.VANILLA_SHOW_FN
    assert data[sp.ADDR_TITLE_STUB : sp.ADDR_TITLE_STUB + sp.TITLE_STUB_LEN] == sp.PATCHED_TITLE_STUB
    assert data[sp.SHOW_APPLY_TAILS[0] : sp.SHOW_APPLY_TAILS[0] + 4] == sp.PATCHED_BX_LR
    assert sp.is_patched(data)


def test_spotpass_skip_rejects_unknown_bytes():
    data = _blob(sp.VANILLA_MOVEQ)
    data[sp.ADDR_MOVEQ] = 0x99
    try:
        sp.apply_patch(data)
    except ValueError as exc:
        assert "unexpected SpotPass no-data store" in str(exc)
    else:
        raise AssertionError("expected ValueError")
