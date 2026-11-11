# Hardening against boot-media attacks

Kon-Boot, Hiren's, Trinity Rescue Kit, a Linux live USB with `chntpw`,
`init=/bin/bash` on the kernel line. All the same attack: boot something
that is not your operating system, and act with authority your login
screen was supposed to gate.

This document is specific about which controls stop it and which do not,
because the difference is stark and most advice blurs it.

---

## 1. How the attack actually works

Kon-Boot loads before the operating system and patches the kernel's
authentication routine **in memory**. On Windows it makes
`MsvpPasswordValidate` return success unconditionally. It writes nothing
to disk, so it leaves almost no trace and survives nothing.

Two consequences follow, and they determine everything below:

- **It needs the authentication routine to exist and to be reachable.**
- **It needs your operating system to boot at all.**

Deny either and it fails.

---

## 2. What works, ranked honestly

### Tier 1 — decisive

**LUKS full-disk encryption with pre-boot authentication.**

This is the control. Everything else in this document is supporting fire.

When the root filesystem is ciphertext, there is no `MsvpPasswordValidate`
to patch, because there is no operating system in memory to patch it in.
The attacker reaches a passphrase prompt for a volume whose key exists only
in your head. Kon-Boot's own documentation concedes it does not work
against full-disk encryption; this is not an accident or an oversight they
will fix, it is structural.

```bash
# At install, in Calamares: tick "Encrypt system".
# Verifying afterwards:
lsblk -o NAME,TYPE,MOUNTPOINT        # look for TYPE=crypt above your root
sudo cryptsetup luksDump /dev/sda3   # PBKDF should be argon2id
```

Choose a passphrase you can actually remember, because there is no
recovery. Five or six unrelated words beats a short mangled one, both for
entropy and for the fact that you will type it at every boot.

> **If you take one thing from this document:** an unencrypted laptop has
> no meaningful login security at all, regardless of how good the password
> is. The password protects a running system. The attacker does not run
> your system.

### Tier 2 — real, but not sufficient alone

**BIOS supervisor password, USB and optical boot disabled, boot order
locked.**

On the AH531: `F2` at power-on, Security tab, set Supervisor Password,
then Boot tab, disable USB and CD/DVD as boot devices, and set Boot Menu
to disabled so `F12` no longer offers a choice.

This is worth doing and takes four minutes. Be clear about its limits:

- On a 2011 consumer laptop, clearing CMOS by removing the coin cell or
  shorting a jumper often clears the supervisor password too.
- Fujitsu machines of this era had known master-password generators
  derived from the challenge code shown after failed attempts.
- It is defeated by a screwdriver and ten minutes.

Treat it as a control that stops an opportunist in a coffee shop and does
not stop anyone determined.

**ATA hard-disk password.** Same BIOS screen. Stronger than the supervisor
password because it is enforced by the drive's own firmware, so moving the
drive to another machine does not help. Still not encryption: on many
drives the password can be cleared with vendor tools, and on some it is
merely gating access to plaintext.

### Tier 3 — defence in depth

**UEFI Secure Boot**, if your unit has UEFI at all. Many AH531s are legacy
BIOS only, so check before relying on it. Signed variants of these tools
have existed, so this raises cost rather than closing the door.

**Encrypted `/boot`.** GRUB can unlock a LUKS volume, which removes the
last unencrypted surface. This closes the evil-maid bootloader-keylogger
gap directly, at the cost of typing the passphrase twice per boot.

---

## 3. What does not work

**A software lockdown that triggers on tampering.** Including the one
shipped in this package, if you misunderstand what it is for.

The reasoning is simple and worth internalising: any service running on
your operating system can be disabled by an attacker who has already
bypassed your operating system's authentication. If Kon-Boot got them an
Administrator shell, they can stop the service, delete the state file, or
simply not boot your OS at all and mount the filesystem from their own.

**A control that runs after the attacker has won cannot stop the attacker
from winning.** Any vendor telling you otherwise is selling theatre.

**Wiping on failed password attempts.** Covered in `security.md`. The
short version: it fires on your typos and never on this attacker, who
never touches a password prompt.

**BIOS password alone.** See Tier 2. A screwdriver.

---

## 4. What the lockdown in this package is actually for

`nemo lock` measures the boot chain and refuses to operate if it changed.
It is **tamper evidence for you**, not a barrier to the attacker, and the
distinction is the whole point.

It is meaningful because of one structural property: **the baseline lives
inside the encrypted volume.** An attacker who boots removable media never
decrypts that volume, so they cannot read the baseline, forge a matching
one, or update it after modifying your bootloader. When you next boot
legitimately and type your passphrase, the comparison happens and the
discrepancy surfaces.

The specific attack it catches is the one encryption alone does not:

> Your encrypted laptop is left in a hotel room. Someone replaces the
> unencrypted `/boot` partition with a bootloader that looks identical and
> logs your passphrase. You return, type your passphrase, and they collect
> it later. Encryption did not fail; it was bypassed by capturing the key
> at entry.

Measuring `/boot`, the EFI boot order, the firmware version and the disk
serials detects exactly that.

```bash
sudo nemo lock baseline      # after a clean install, before travel
nemo lock status             # what is being measured, and whether it matches
sudo nemo lock check         # what the boot service runs
nemo admin login && nemo lock unlock   # after investigating
```

Arm it **after** encrypting, not before. `nemo lock baseline` refuses on an
unencrypted root and tells you why: an unencrypted baseline is one the
attacker can rewrite, which would make the whole mechanism a formality.

---

## 5. The configuration to actually run

In order. Each step assumes the previous.

1. **Reinstall with LUKS.** Not optional, and not retrofittable in place
   without significant effort. This is the step that matters.
2. **Set a BIOS supervisor password**, disable USB and optical boot,
   disable the boot menu key.
3. **Set an ATA hard-disk password** on the same screen.
4. **Arm the boot baseline**: `sudo nemo lock baseline`.
5. **Set the admin credential**: `nemo admin init`.
6. **Test the lock**: change something harmless in `/boot`, reboot, confirm
   Nemo refuses to run and names the change. Then unlock. A tamper alarm
   you have never seen fire is an alarm you do not know works.
7. **Back up off the machine.** Every control above increases the chance of
   permanently losing access to your own data. Encryption with no backup is
   a way to lose work, not protect it.

---

## 6. What is still true afterwards

**An unlocked running machine is fully exposed.** Encryption protects data
at rest. Lock the screen; set it to lock on lid close.

**A cold-boot attack against RAM is possible in principle.** Not a
realistic threat to a hobby workshop, mentioned for completeness.

**None of this protects against you.** The most likely way this machine
loses data remains an accidental `rm`, a failed fourteen-year-old drive, or
a forgotten passphrase. Backups address all three; none of the controls
above address any of them.
