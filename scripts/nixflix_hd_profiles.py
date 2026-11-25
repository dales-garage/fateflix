#!/usr/bin/env python3
"""Preserve FateFlix HD codec preferences through Recyclarr syncs."""
import argparse
import copy
import json
import os
from pathlib import Path
import tempfile
import urllib.request

EXTRA_FORMATS = {
    "[FateFlix] H264": [r"\b(?:[xh][ ._-]?264|avc)\b"],
    "[FateFlix] AV1 MP4": [r"\bAV1\b", r"\bmp4\b"],
}

def validate(policy):
    for p in policy["profiles"].values():
        scores = {x["name"]: x["score"] for x in p["guide_scores"]}
        secondary = sum(v for k, v in scores.items() if k not in ("AV1", "x265 (HD)"))
        assert 0 <= secondary <= 499
        av1, hevc = scores["AV1"], scores["x265 (HD)"]
        h264 = p["extra_scores"]["[FateFlix] H264"]
        bonus = p["extra_scores"]["[FateFlix] AV1 MP4"]
        assert av1 + bonus > av1 + secondary
        assert av1 > hevc + secondary > h264 + secondary > secondary
        assert hevc > h264 + secondary and h264 > secondary
        assert -10000 + av1 + bonus + secondary < p["min_format_score"]
        assert av1 + secondary < p["cutoff_format_score"] <= av1 + bonus

def configure(config, policy):
    result = copy.deepcopy(config)
    for app, p in policy["profiles"].items():
        instance = result[app][app]
        profile = next(x for x in instance["quality_profiles"] if x.get("trash_id") == p["trash_id"])
        profile["min_format_score"] = p["min_format_score"]
        profile.setdefault("upgrade", {}).update(allowed=True, until_score=p["cutoff_format_score"])
        reset = profile.setdefault("reset_unmatched_scores", {})
        reset["except"] = sorted(set(reset.get("except", [])) | set(EXTRA_FORMATS))
        formats = instance.setdefault("custom_formats", [])
        managed_ids = {x["trash_id"] for x in p["guide_scores"]}
        # Our entries use profile-local scores; remove those entries before replacing.
        formats[:] = [x for x in formats if not (
            len(x.get("trash_ids", [])) == 1 and x["trash_ids"][0] in managed_ids
            and len(x.get("assign_scores_to", [])) == 1
            and x["assign_scores_to"][0].get("trash_id") == p["trash_id"]
        )]
        for score in p["guide_scores"]:
            formats.append({"trash_ids": [score["trash_id"]], "assign_scores_to": [
                {"trash_id": p["trash_id"], "score": score["score"]}]})
    return result

def atomic_json(path, value):
    info = path.stat()
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, info.st_mode & 0o777)
        if os.geteuid() == 0:
            os.chown(temporary, info.st_uid, info.st_gid)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

def apply(config, policy):
    for app, p in policy["profiles"].items():
        instance = config[app][app]
        def api(resource, method="GET", payload=None):
            request = urllib.request.Request(
                instance["base_url"].rstrip("/") + "/api/v3/" + resource,
                data=None if payload is None else json.dumps(payload).encode(),
                headers={"X-Api-Key": instance["api_key"], "Content-Type": "application/json"},
                method=method,
            )
            with urllib.request.urlopen(request, timeout=15) as response:
                raw = response.read()
            return json.loads(raw) if raw else None
        formats = api("customformat")
        for name, expressions in EXTRA_FORMATS.items():
            definition = {"name": name, "includeCustomFormatWhenRenaming": False,
                "specifications": [{"name": "Match " + str(i + 1),
                    "implementation": "ReleaseTitleSpecification", "negate": False,
                    "required": True, "fields": [{"name": "value", "value": expression}]}
                    for i, expression in enumerate(expressions)]}
            existing = next((x for x in formats if x["name"] == name), None)
            if existing:
                actual = [(x["implementation"], x.get("negate", False), x.get("required", False),
                    next(f["value"] for f in x["fields"] if f["name"] == "value")) for x in existing["specifications"]]
                desired = [("ReleaseTitleSpecification", False, True, e) for e in expressions]
                if actual != desired:
                    definition["id"] = existing["id"]
                    api("customformat/" + str(existing["id"]), "PUT", definition)
            else:
                api("customformat", "POST", definition)
        profiles = api("qualityprofile")
        profile = next(x for x in profiles if x["name"] == p["profile_name"])
        scores = {x["name"]: x["score"] for x in p["guide_scores"]} | p["extra_scores"]
        present = {x["name"] for x in profile["formatItems"]}
        if not scores.keys() <= present:
            raise ValueError("Missing expected HD custom format")
        for item in profile["formatItems"]:
            if item["name"] in scores:
                item["score"] = scores[item["name"]]
        other_positive = sum(x["score"] for x in profile["formatItems"] if x["score"] > 0
            and x["name"] not in ("AV1", "x265 (HD)", *EXTRA_FORMATS))
        if other_positive > 499:
            raise ValueError("Unexpected secondary scores exceed codec preference budget")
        profile.update(minFormatScore=p["min_format_score"], cutoffFormatScore=p["cutoff_format_score"], upgradeAllowed=True)
        api("qualityprofile/" + str(profile["id"]), "PUT", profile)
        print(app + ": HD codec preference applied")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--configure", action="store_true")
    operation.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    policy = json.loads(args.policy.read_text())
    validate(policy)
    config = json.loads(args.config.read_text())
    if args.configure:
        atomic_json(args.config, configure(config, policy))
    else:
        apply(config, policy)

if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("HD profile update failed: " + type(error).__name__)
        raise SystemExit(1)
