#!/usr/bin/env python3
"""Pure launch-input/compiled-ABI checks; no successful service responses or RPC substitutions."""
import copy
import json
import tempfile
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import release


class LaunchValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.main = json.loads((release.ROOT / "deploy/mainnet.json").read_text())
        cls.manager = json.loads((release.ROOT / "deploy/manager.json").read_text())
        # Positive proof uses the actual current compiler output, never a hand-written ABI.
        cls.vault_abi = release.artifact("PackVault")["abi"]
        cls.factory_abi = release.artifact("PackManagerFactory")["abi"]

    def test_current_values_and_actual_compiled_abi(self):
        release.validate_launch_values(self.main)
        release.validate_launch_values(self.manager, manager=True)
        release.validate_compiled_launch_abi(self.vault_abi, self.factory_abi)
        release.validate_launch_inputs()

    def test_launch_requirement_is_independent_of_matching_values_and_manifest(self):
        # A regenerated manifest can bind a wrong file perfectly. Launch identity still rejects it.
        wrong = copy.deepcopy(self.main)
        wrong["packUnitsMask"] = 64
        with self.assertRaisesRegex(ValueError, "mask 8.*units 3"):
            release.validate_launch_values(wrong)
        wrong = copy.deepcopy(self.manager)
        wrong["packUnitsMask"] = 64
        with self.assertRaisesRegex(ValueError, "mask 8"):
            release.validate_launch_values(wrong, manager=True)

    def test_exact_main_dependencies_including_main_shape_packs(self):
        for key in release.MAIN_DEPENDENCIES:
            with self.subTest(dependency=key):
                wrong = copy.deepcopy(self.main)
                wrong[key] = "0x" + "11" * 20
                with self.assertRaisesRegex(ValueError, "main-pool dependency"):
                    release.validate_launch_values(wrong)
        # The actual community ShapePacks must not become main by matching a self-consistent file/readback.
        wrong = copy.deepcopy(self.main)
        wrong["packs"] = "0xfE11c0E794475fd86801fb3020d779bd7887cB2D"  # deployed community ShapePacks
        with self.assertRaisesRegex(ValueError, "launch packs"):
            release.validate_launch_values(wrong)

    def test_every_numeric_parameter_is_required_without_defaults(self):
        for manager, original in ((False, self.main), (True, self.manager)):
            for key, _ in release.PARAM_FIELDS:
                with self.subTest(manager=manager, missing=key):
                    wrong = copy.deepcopy(original)
                    del wrong[key]
                    with self.assertRaisesRegex(ValueError, "missing"):
                        release.validate_launch_values(wrong, manager=manager)

    def test_all_28_gas_fields_are_required_and_no_unknown_key_is_ignored(self):
        self.assertEqual(len(release.GAS_FIELDS), 28)
        for key in release.GAS_FIELDS:
            with self.subTest(missing=key):
                wrong = copy.deepcopy(self.main)
                del wrong["gasSchedule"][key]
                with self.assertRaisesRegex(ValueError, "gasSchedule keys.*missing"):
                    release.validate_launch_values(wrong)
        for key in ("obsoletePolicyGas", "checkpont"):
            wrong = copy.deepcopy(self.main)
            wrong["gasSchedule"][key] = 1
            with self.assertRaisesRegex(ValueError, "unexpected"):
                release.validate_launch_values(wrong)
        wrong = copy.deepcopy(self.main)
        wrong["allocatedBoundBps"] = wrong.pop("upliftBoundBps")
        with self.assertRaisesRegex(ValueError, "upliftBoundBps"):
            release.validate_launch_values(wrong)

    def test_json_numbers_are_exact_unsigned_values_not_coercions(self):
        for bad in (True, "500000", 500000.5, -1, 1 << 32):
            with self.subTest(value=bad):
                wrong = copy.deepcopy(self.main)
                wrong["gasSchedule"]["checkpoint"] = bad
                with self.assertRaisesRegex(ValueError, "unsigned 32-bit JSON integer"):
                    release.validate_launch_values(wrong)
        wrong = copy.deepcopy(self.main)
        wrong["reserveWei"] = 1 << 128
        with self.assertRaisesRegex(ValueError, "reserveWei"):
            release.validate_launch_values(wrong)

    def test_expected_mint_fee_is_required_and_separate_from_acceptance(self):
        wrong = copy.deepcopy(self.main)
        del wrong["expectedMintFeeWei"]
        with self.assertRaisesRegex(ValueError, "expectedMintFeeWei"):
            release.validate_launch_values(wrong)
        wrong = copy.deepcopy(self.main)
        wrong["expectedMintFeeWei"] = wrong["acceptedMintFeeWei"] + 1
        with self.assertRaisesRegex(ValueError, "explicitly accepted maximum"):
            release.validate_launch_values(wrong)

    def test_owner_and_provisional_economics_remain_data_not_immutable_choices(self):
        changed = copy.deepcopy(self.main)
        changed["owner"] = "0x" + "ab" * 20
        changed["backingRatioBps"] = 80_000
        changed["upliftBoundBps"] = 30
        changed["gasSchedule"]["build"] += 1000
        release.validate_launch_values(changed)
        # Launch-tool mask validation does not add contract-level restrictions on later owner updates.
        self.assertEqual(release.LAUNCH_UNITS, 3)

    def test_duplicate_json_fields_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "values.json"
            path.write_text('{"packUnitsMask":8,"packUnitsMask":64}')
            with self.assertRaisesRegex(ValueError, "duplicate launch JSON key"):
                release._launch_json(path)

    def test_stale_same_width_params_name_and_reordered_names_fail(self):
        for change in ("rename", "reorder", "omit"):
            with self.subTest(change=change):
                wrong = copy.deepcopy(self.vault_abi)
                getter = next(entry for entry in wrong if entry.get("name") == "getParams")
                fields = getter["outputs"][0]["components"]
                if change == "rename":
                    fields[5]["name"] = "allocatedBoundBps"
                elif change == "reorder":
                    fields[0], fields[1] = fields[1], fields[0]
                else:
                    fields.pop(20)
                with self.assertRaisesRegex(ValueError, "Params names/types/order"):
                    release.validate_compiled_launch_abi(wrong, self.factory_abi)

    def test_stale_nested_gas_name_type_order_or_missing_field_fail(self):
        for change in ("rename", "type", "reorder", "omit"):
            with self.subTest(change=change):
                wrong = copy.deepcopy(self.vault_abi)
                getter = next(entry for entry in wrong if entry.get("name") == "getParams")
                gas = getter["outputs"][0]["components"][-1]["components"]
                if change == "rename":
                    gas[0]["name"] = "oldCheckpoint"
                elif change == "type":
                    gas[0]["type"] = "uint64"
                elif change == "reorder":
                    gas[0], gas[1] = gas[1], gas[0]
                else:
                    gas.pop()
                with self.assertRaisesRegex(ValueError, "GasSchedule names/types/order"):
                    release.validate_compiled_launch_abi(wrong, self.factory_abi)

    def test_old_constructor_and_factory_policy_argument_fail(self):
        wrong = copy.deepcopy(self.vault_abi)
        constructor = next(entry for entry in wrong if entry["type"] == "constructor")
        constructor["inputs"].pop()
        with self.assertRaisesRegex(ValueError, "six guarded inputs"):
            release.validate_compiled_launch_abi(wrong, self.factory_abi)
        wrong = copy.deepcopy(self.factory_abi)
        create = next(entry for entry in wrong if entry.get("name") == "create")
        create["inputs"].insert(2, {"name": "policy", "type": "address"})
        with self.assertRaisesRegex(ValueError, "only.*owner, p, expected"):
            release.validate_compiled_launch_abi(self.vault_abi, wrong)

    def test_factory_and_constructor_nested_params_are_also_checked(self):
        wrong = copy.deepcopy(self.factory_abi)
        create = next(entry for entry in wrong if entry.get("name") == "create")
        create["inputs"][1]["components"][0]["type"] = "uint32"
        with self.assertRaisesRegex(ValueError, "factory create Params"):
            release.validate_compiled_launch_abi(self.vault_abi, wrong)
        wrong = copy.deepcopy(self.vault_abi)
        constructor = next(entry for entry in wrong if entry["type"] == "constructor")
        constructor["inputs"][4]["components"][-1]["components"].pop()
        with self.assertRaisesRegex(ValueError, "PackVault constructor GasSchedule"):
            release.validate_compiled_launch_abi(wrong, self.factory_abi)


if __name__ == "__main__":
    unittest.main()
