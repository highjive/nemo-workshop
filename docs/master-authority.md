# Master authority

Two tiers of administrator, and a hard limit above both.

| Tier | Who | Can do | Cannot do |
|---|---|---|---|
| Local admin | The person running the machine | View the effective parameters; **tighten** any of them | Loosen anything |
| Master | Holder of the private key | Issue a signed floor that replaces the defaults, in either direction | Cross the hard floor |
| — | Nobody | — | `HARD_FLOOR` in `nemo/safety.py` |

## Why this is signatures and not a master password

A password that ships inside a cloned image is a secret on a disk the
recipient owns. They do not crack it; they overwrite the credential file
with a hash of a password they chose, and they are master on their copy.
Increasing the hash cost changes nothing, because cracking was never the
attack.

Signatures invert this. **Nothing secret ships.** The image carries only a
public key, which reveals nothing and cannot be used to forge anything. The
private key stays on your machine and never travels. A floor change is a
signed document you can email, publish, or leave on a bench — it is useless
for producing a different one.

## Setup, once

```bash
tools/master-key.py generate            # on YOUR machine, not a target
tools/master-key.py embed dist/NemoIso  # public key into the build
```

Back the private key up offline before shipping anything. If you lose it,
you can no longer issue floor documents for installs already in the field;
if it leaks, anyone can sign as you and the only remedy is a new release
with a new public key.

Check a build is yours by comparing fingerprints:

```bash
nemo master status        # prints the embedded key's fingerprint
```

## Issuing a floor change

```bash
tools/master-key.py sign new-floor.yaml 4
# -> floor-4.signed.json
```

The serial must increase. An install already holding serial 4 refuses a
document with serial 3, so a legitimately-signed but permissive older
document cannot be replayed to roll a deployed floor backwards.

## Applying one, physically

```bash
nemo master apply /media/usb/floor-4.signed.json
```

Two checks before it will run, both by request and both worth having:

- **Local console.** Refused over SSH or from a script. This genuinely
  removes remote application as an attack path.
- **Removable media.** The document must be on a USB stick, not on the
  system disk.

Neither constrains the person holding the laptop. Nothing can.

## The hard floor

Some parameters are above master authority. A signed document that tries to
change them is applied, and the overstepped fields are clamped and
reported — you are told your document was partly ignored rather than it
failing silently.

- The three human sign-off gates (print, order, battery connect)
- Tier 0 checks remaining mandatory
- Mains voltage requiring qualified review
- LiPo protection circuits
- The 48 V ceiling — a signed floor may lower it, nothing raises it
- The weapons, medical-implant and life-support domain entries

This exists because an authority with no ceiling is a single point of
failure, and you are not exempt from that. A mistaken document, a leaked
key, or a bad day should not be able to turn this into something that
designs a weapon or skips the battery gate.

## Cloning

```bash
nemo clone /media/usb/nemo-clone     # stage a clean copy
# then, on a faster machine:
cd /media/usb/nemo-clone && sudo packaging/build-iso.sh live
```

Staging runs on the AH531; building the image does not. live-build needs
root, several gigabytes of scratch space and a long time on two cores.

Carried into the clone: the signed floor, the local policy, the parts
library, the prompts, the embedded public key.

**Dropped from every clone**, because carrying them is a real bug rather
than an oversight:

| Dropped | Why |
|---|---|
| `admin.cred` | Every clone would otherwise share one admin password |
| `admin.state` | Failure counters from someone else's machine |
| `audit.log` | The source machine's history is not the clone's |
| `boot.baseline` | Hardware differs; every clone would lock on first boot |
| `lock.state` | Follows the baseline |

Each clone's recipient runs `nemo admin init` and sets their own local
admin, which cannot loosen anything.

## What this does not do

It does not stop the holder of an image from editing `nemo/safety.py`,
replacing the embedded public key with their own, or deleting the
verification. On hardware someone else controls, no software control
survives a determined owner — the same result as the boot-media analysis in
`hardening.md`, and equally unfixable.

Signature verification protects the integrity of an install running your
code. It is **authenticity, not enforcement**. What it gives you that a
password cannot: a clone cannot be silently reconfigured and still claim to
be yours, and you can demonstrate which floor an install was actually
running. Anyone claiming software can enforce a policy on hardware they do
not control is describing DRM, which has never worked.

---

# Maintenance mode

For when a clone misbehaves and needs to be stopped and diagnosed rather
than wiped. Nothing in this section deletes user data.

## The workflow

1. **On the clone**, the user reads out its identity:

   ```
   nemo maint status
   clone id    : 23f52239-8155-4b15-9ae0-5066090d3216
   master key  : 0ce8-e47c-1361-d3b8
   ```

   The master-key fingerprint should match yours. If it does not, that
   build was not made by you, and nothing you sign will act on it.

2. **On your machine**, you issue an operation for that clone:

   ```bash
   tools/master-key.py op halt 23f52239-8155-4b15-9ae0-5066090d3216 24
   ```

3. **At the clone**, from a USB stick:

   ```bash
   nemo maint apply /media/usb/halt-23f52239.op.json
   ```

4. **Diagnose**, which anyone may run:

   ```bash
   nemo maint diagnose        # writes nemo-diagnose-<date>.zip
   ```

5. **Resume or reset**, with a fresh document for each.

## The three operations

| Action | Effect | Touches user data? |
|---|---|---|
| `halt` | Disables the design pipeline. Diagnosis, status and admin commands stay available. | No |
| `resume` | Lifts a halt. | No |
| `reset` | Clears local policy, lock state, boot baseline and running mode. Lifts any halt. Keeps a `*.pre-reset-*` copy of everything it clears. | No |

`reset` deliberately **keeps the audit log**. It is the record of the fault
being diagnosed, and clearing it would destroy the evidence at exactly the
moment it is needed.

## Three properties every document has

These are not optional, and each one exists because leaving it out turns
the maintenance system into a weapon against your own clones.

**Bound to one clone.** Each install generates a random ID on first use. A
document names the ID it is for and refuses to act anywhere else. Without
this, one signed halt would stop every clone in existence, and one leaked
copy would be a universal kill switch. Target `*` exists for genuinely
fleet-wide action and requires typing `EVERY` to issue.

**Expires.** 24 hours by default, 7 days maximum regardless of what is
requested. A document issued for last spring's fault must not still work
next year.

**Works once.** Each document carries a random nonce, recorded on use. The
same document presented twice is refused, so a captured halt cannot be
replayed to stop a clone again after it has been fixed.

A clone's ID, halt state and used-nonce list are **excluded from clones**.
If a clone inherited its source's ID, a document for one would act on both
and target binding would silently stop working. A test demonstrates this.

## Diagnostic bundles are safe to send

`nemo maint diagnose` never includes the credential hash, live session
tokens, the used-nonce list, API keys, or project contents. The bundle
contains an `EXCLUDED.txt` that says so. It does include the audit log,
maintenance history, configuration, doctor output and logs, which is what
diagnosis actually needs.

## What halt is

A cooperative stop. An unmodified clone honours it; a clone whose owner has
edited the code can ignore it, the same limit that applies to everything in
this document.

For this purpose that limit barely matters. Maintenance mode exists to
diagnose a malfunctioning clone, where the clone is not an adversary and
wants to be fixed. Cooperation is the right model here, and it is the
reason this works well where the safety floor could only ever be
authenticity.
