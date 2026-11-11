#!/usr/bin/env python3
"""Author-side master key tooling. Never run this on a target install.

    tools/master-key.py generate               create the keypair
    tools/master-key.py embed <build-dir>      put the PUBLIC key in a build
    tools/master-key.py sign <floor.yaml> <n>  sign a floor document
    tools/master-key.py op <action> <clone-id> [hours]
                                               halt | resume | reset a clone
                                               revoke asks for the nonce of
                                               the document it neutralises

The private key stays on your machine. It is the only thing in this whole
system that must not be copied, and losing it means you can no longer issue
floor documents for existing installs -- so back it up somewhere offline
before you ship anything.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import yaml
from nemo.signing import (generate_master_key, public_key_fingerprint,
                          sign_floor)
from nemo.maintenance import sign_operation, WILDCARD

HOME = Path.home() / ".nemo-master"
PRIV, PUB = HOME / "master.key", HOME / "master.pub"


def cmd_generate():
    if PRIV.exists():
        sys.exit(f"{PRIV} already exists. Generating again would orphan every "
                 "install that trusts the current key. Delete it deliberately "
                 "if that is what you want.")
    generate_master_key(PRIV, PUB)
    pub = PUB.read_text().strip()
    print(f"private key : {PRIV}   <- back this up offline, never ship it")
    print(f"public key  : {PUB}")
    print(f"fingerprint : {public_key_fingerprint(pub)}")
    print("\nCheck that fingerprint against 'nemo master status' on any build")
    print("to confirm it is yours.")


def cmd_embed(build_dir):
    if not PUB.exists():
        sys.exit("no public key yet. Run: tools/master-key.py generate")
    pub = PUB.read_text().strip()
    target = Path(build_dir) / "nemo" / "master.py"
    if not target.exists():
        sys.exit(f"not a Nemo build: {target} missing")
    text = target.read_text()
    text = text.replace('MASTER_PUBLIC_KEY = ""',
                        f'MASTER_PUBLIC_KEY = "{pub}"')
    target.write_text(text)
    print(f"embedded {public_key_fingerprint(pub)} into {target}")
    print("This is a PUBLIC key. Shipping it in every clone is safe and is")
    print("the entire reason this design uses signatures and not a password.")


def cmd_sign(floor_path, serial):
    if not PRIV.exists():
        sys.exit("no private key. Run: tools/master-key.py generate")
    values = yaml.safe_load(Path(floor_path).read_text())
    if not isinstance(values, dict):
        sys.exit("the floor file must be a YAML mapping")
    note = input("note (what changed and why): ").strip()
    doc = sign_floor(PRIV, values, int(serial), note)
    out = Path(f"floor-{serial}.signed.json")
    out.write_text(doc.to_json())
    print(f"\nwrote {out}")
    print(f"serial {serial}. An install already holding a higher serial will")
    print("refuse this document, so increment it on every issue.")
    print("\nCarry it to the machine on a USB stick and run:")
    print(f"  nemo master apply /media/<stick>/{out.name}")


def cmd_op(action, target, hours="24"):
    if not PRIV.exists():
        sys.exit("no private key. Run: tools/master-key.py generate")
    if target == WILDCARD:
        confirm = input("Target '*' acts on EVERY clone that sees this "
                        "document. Type EVERY to confirm: ")
        if confirm.strip() != "EVERY":
            sys.exit("cancelled")
    target_nonce = ""
    if action == "revoke":
        target_nonce = input("nonce of the document to revoke (from its "
                             "own .op.json, or the copy you kept when you "
                             "signed it): ").strip()
        if not target_nonce:
            sys.exit("a revoke needs the nonce of the document it revokes")
    note = input("note (what is wrong, and why this action): ").strip()
    doc = sign_operation(PRIV, action, target, float(hours), note, target_nonce)
    out = Path(f"{action}-{target[:8]}.op.json")
    out.write_text(doc.to_json())
    hrs = (doc.expires_at - doc.issued_at) / 3600
    print(f"\nwrote {out}")
    print(f"  valid for {hrs:.0f}h, usable once, only on clone {target[:8]}...")
    print("\nOn the clone, from a USB stick at the machine:")
    print(f"  nemo maint apply /media/<stick>/{out.name}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd = sys.argv[1]
    if cmd == "generate":
        cmd_generate()
    elif cmd == "embed" and len(sys.argv) == 3:
        cmd_embed(sys.argv[2])
    elif cmd == "sign" and len(sys.argv) == 4:
        cmd_sign(sys.argv[2], sys.argv[3])
    elif cmd == "op" and len(sys.argv) in (4, 5):
        cmd_op(*sys.argv[2:])
    else:
        sys.exit(__doc__)
