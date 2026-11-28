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

    def test_all_29_gas_fields_are_required_and_no_unknown_key_is_ignored(self):
        self.assertEqual(len(release.GAS_FIELDS), 29)
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


class ManagerDeploymentTests(unittest.TestCase):
    """Pure artifact/encoding checks; integration still requires actual deployment receipts."""
    @classmethod
    def setUpClass(cls):
        cls.factory = release._launch_json(release.ROOT / "deploy/manager-factory.json")
        cls.manager_abi = release.artifact("PackManager")["abi"]
        cls.factory_abi = release.artifact("PackManagerFactory")["abi"]
        cls.compiled = release.build("manager")

    def test_manager_target_has_no_vault_seed_owner_or_global_economics(self):
        release.validate_manager_factory_values(self.factory)
        release.validate_launch_inputs(target="manager")
        for key, value in (("seedWei", 10**16), ("owner", "0x" + "ab"*20), ("packUnitsMask", 8)):
            bad = self.factory | {key: value}
            with self.assertRaisesRegex(ValueError, "unexpected"):
                release.validate_manager_factory_values(bad)
        for key, value in (("target", "combined"), ("packs", "0xfE11c0E794475fd86801fb3020d779bd7887cB2D")):
            with self.assertRaises(ValueError):
                release.validate_manager_factory_values(self.factory | {key: value})

    def test_target_selection_and_approvals_cannot_fall_back_to_combined(self):
        self.assertEqual(release.parse_target(["--target", "manager", "x"]), ("manager", ["x"]))
        self.assertEqual(release.parse_target(["x", "--broadcast"]), ("combined", ["x", "--broadcast"]))
        for args in (["--target"], ["--target", "managers"], ["--target", "manager", "--target", "combined"]):
            with self.assertRaises(ValueError):
                release.parse_target(args)
        combined = release.target_files("combined")
        manager = release.target_files("manager")
        for index in (0, 1, 2, 5):
            self.assertNotEqual(combined[index], manager[index])
        self.assertEqual(manager[5], "deploy/manager-factory.json")

    def test_manager_build_contains_only_manager_product_and_same_shared_libraries(self):
        self.assertEqual(set(self.compiled), {"PackManager", "PackManagerFactory", *release.LIBRARIES})
        combined = release.build()
        for name, compiled in self.compiled.items():
            self.assertEqual(compiled, combined[name])
            self.assertLessEqual(compiled["runtime_bytes"], release.CODE_LIMIT)

    def test_actual_manager_compiled_abi_checks_getter_and_initialization(self):
        release.validate_compiled_manager_abi(self.manager_abi, self.factory_abi)
        for name in ("getParams", "initialize"):
            bad = copy.deepcopy(self.manager_abi)
            entry = next(e for e in bad if e.get("name") == name)
            params = entry["outputs"][0] if name == "getParams" else entry["inputs"][1]
            params["components"][-1]["components"][2]["name"] = "staleGasField"
            with self.assertRaisesRegex(ValueError, "GasSchedule names/types/order"):
                release.validate_compiled_manager_abi(bad, self.factory_abi)
        bad = copy.deepcopy(self.factory_abi)
        next(e for e in bad if e.get("name") == "create")["inputs"].insert(2, {"name": "policy", "type": "address"})
        with self.assertRaisesRegex(ValueError, "only.*owner, p, expected"):
            release.validate_compiled_manager_abi(self.manager_abi, bad)
        bad = copy.deepcopy(self.manager_abi)
        next(e for e in bad if e.get("type") == "constructor")["inputs"].append({"name": "policy", "type": "address"})
        with self.assertRaisesRegex(ValueError, "manager constructor"):
            release.validate_compiled_manager_abi(bad, self.factory_abi)

    def test_migration_surface_and_retired_renewal_cannot_hide_in_old_abi(self):
        for name in ('importPacks','unlistForWithdrawal'):
            bad=[e for e in self.manager_abi if e.get('name') != name]
            with self.assertRaisesRegex(ValueError,name):
                release.validate_compiled_manager_abi(bad,self.factory_abi)
        for name in ('renew','renewalFloat','renewalEligible'):
            bad=copy.deepcopy(self.manager_abi)+[{'type':'function','name':name,'inputs':[],'outputs':[]}]
            with self.assertRaisesRegex(ValueError,'retired'):
                release.validate_compiled_manager_abi(bad,self.factory_abi)

    def _encoded_run(self):
        from eth_abi import encode
        addresses = {name: bytes.fromhex(self.compiled[name]["create2_address"][2:]) for name in release.LIBRARIES}
        rows = []
        for index, name in enumerate([*release.LIBRARIES, "PackManagerFactory"]):
            bytecode = release.artifact(name)["bytecode"]
            init = release.linked(bytecode["object"], bytecode.get("linkReferences", {}), addresses)
            library = name in release.LIBRARIES
            data = bytes(32) + init if library else init + encode(["address"]*3, [self.factory[k] for k in release.MAIN_DEPENDENCIES])
            tx = dict(from_="0x" + "ab"*20, chainId="0x1", nonce=hex(index + 100), gas=hex(10_000_000), input="0x"+data.hex())
            tx["from"] = tx.pop("from_")
            if library:
                tx["to"] = release.CREATE2_FACTORY
            rows.append(dict(contractName=name, transactionType="CREATE2" if library else "CREATE", hash=None,
                             contractAddress=self.compiled[name]["create2_address"] if library else release.create_address(tx["from"], index + 100),
                             transaction=tx))
        return dict(chain=1, receipts=[], transactions=rows)

    def test_unsigned_factory_encoding_matches_real_compiled_artifacts(self):
        rows, reused = release.validate_manager_transactions(self._encoded_run(), self.factory, self.compiled)
        self.assertEqual(len(rows), 4)
        self.assertEqual(reused, [])
        self.assertEqual(rows[-1]["contract"], "PackManagerFactory")
        self.assertNotIn("value", rows[-1]["unsignedTransaction"])
        run = self._encoded_run()
        run["transactions"] = run["transactions"][-1:]
        rows, reused = release.validate_manager_transactions(run, self.factory, self.compiled)
        self.assertEqual(reused, release.LIBRARIES)
        self.assertEqual(len(rows), 1)

    def test_unsigned_encoder_rejects_seed_vault_signatures_and_wrong_chain(self):
        variants = []
        run = self._encoded_run(); run["transactions"][-1]["transaction"]["value"] = hex(10**16); variants.append(run)
        run = self._encoded_run(); run["transactions"][-1]["contractName"] = "PackVault"; variants.append(run)
        run = self._encoded_run(); run["transactions"][-1]["hash"] = "0x"+"11"*32; variants.append(run)
        run = self._encoded_run(); run["transactions"][-1]["transaction"]["v"] = "0x1"; variants.append(run)
        run = self._encoded_run(); run["chain"] = 31337; variants.append(run)
        run = self._encoded_run(); run["chain"] = True; variants.append(run)
        run = self._encoded_run(); run["transactions"][-1]["transaction"]["chainId"] = "0x7a69"; variants.append(run)
        run = self._encoded_run(); run["transactions"][-1]["transaction"]["gas"] = hex(16_777_217); variants.append(run)
        for run in variants:
            with self.assertRaises(ValueError):
                release.validate_manager_transactions(run, self.factory, self.compiled)

    def test_unsigned_encoder_rejects_wrong_links_calldata_and_nonce_order(self):
        variants = []
        run = self._encoded_run(); run["transactions"][-1]["transaction"]["input"] += "00"; variants.append(run)
        run = self._encoded_run(); run["transactions"][1]["contractAddress"] = "0x"+"11"*20; variants.append(run)
        run = self._encoded_run(); run["transactions"][-1]["contractAddress"] = "0x"+"11"*20; variants.append(run)
        run = self._encoded_run(); run["transactions"][-1]["transaction"]["nonce"] = "0x999"; variants.append(run)
        run = self._encoded_run(); run["transactions"][-1]["transaction"]["from"] = "0x"+"11"*20; variants.append(run)
        run = self._encoded_run(); run["transactions"][0], run["transactions"][1] = run["transactions"][1], run["transactions"][0]; variants.append(run)
        run = self._encoded_run(); run["transactions"].pop(); variants.append(run)
        for run in variants:
            with self.assertRaises(ValueError):
                release.validate_manager_transactions(run, self.factory, self.compiled)

    def test_manager_clone_runtime_has_exact_implementation_slot(self):
        implementation = "0x"+"ab"*20
        runtime = bytes.fromhex(release.clone_runtime(implementation)[2:])
        self.assertEqual(len(runtime), 44)
        self.assertEqual(runtime[11:31], bytes.fromhex(implementation[2:]))

    def test_factory_prediction_matches_independent_cast_implementation(self):
        import subprocess
        sender = "0x" + "ab"*20
        for nonce in (0, 1, 103, (1 << 64) - 1):
            actual = subprocess.check_output(["cast", "compute-address", sender, "--nonce", str(nonce)], text=True)
            self.assertEqual(release.create_address(sender, nonce), actual.split()[-1].lower())
        with self.assertRaisesRegex(ValueError, "64-bit"):
            release.create_address(sender, 1 << 64)



if __name__ == "__main__":
    unittest.main()
