# A tool to "edit" Ubuntu live server CDs

There are a few reasons the Ubuntu live server ISOs as shipped may not
quite be what you want. Here are some examples:

 * You want to make an ISO that does a completely automated install

 * You want packages that are not in the package repository by default
   to be available during install, even when there is no network (or
   only a very isolated network).

 * You want to add an argument to the default kernel command line.

 * You want to inject a new version of the subiquity snap for testing.

This script aims to help you making modified versions of the
distributed ISOs with changes such as those above.

Some of the things it does probably work on desktop installer ISOs too
but I haven't thought very hard about that side of things yet.

## Dependencies

This script is pretty Linux-dependent and requires `xorriso` and
`mksquashfs` to be available on `$PATH`.  Some actions require the
`python3-debian` package to be installed and `gpg` command to be
available.

It needs to be run as root (although possibly using FUSE variants for
all the mounts would allow it to run as a regular user, maybe).

## General invocation

The basic idea behind this tool is that you tell it where to find the
source ISO, where to put the modified ISO and a list of actions that
make up the modifications. So an invocation always looks somewhat like
this:

```
# livefs-edit $source.iso $dest.iso [actions]
```

Actions can be specified two ways: on the command line or in a YAML
file. Each action has a name and many of them take arguments.

On the command line, actions and arguments are specified like:

```
--action-name arg1 arg2 --next-action-name
```

Arguments can be passed positionally:

```
--cp source/path dest/path
```

Or by name:

```
--cp source=source/path dest=dest/path
```

Apart from arguments that are a list, such as a list of package
names. These are always the last (in fact only, at the time of writing)
argument and are just space separated:

```
--add-packages-to-pool binutils gdb
```

Alternatively (if shell quoting starts to get painful), the actions
can be passed as a YAML file, using the `--action-yaml` flag:

```
# livefs-edit $source.iso $dest.iso --action-yaml examples/example.yaml
```

The YAML file should be a list of mappings. Each mapping names the
actions with `name` and lists any arguments by name, for example:

```
- name: add-cmdline-arg
  arg: autoinstall
  persist: false
- name: shell
- name: add-packages-to-pool
  packages:
    - casper
    - valgrind
```

## Directory structure

This script does all its work in a temporary directory. Within that
directory the original ISO is mounted at `old/iso` and what will be
packed into the new ISO is present at `new/iso` (the script uses a lot
of `overlayfs` mounts to avoid copying large amounts of data around,
and also only repack things when there are changes).

Many actions require a writable emulation of the root filesystem that
the installer will run in. By default this is created at `rootfs` in
the main temporary directory, but this can be customized.

In general, things from the original ISO are mounted in `old/` and are
either read-only or should be treated as such. Writable versions for
the new ISO live in `new/` (mostly).

## Actions

### setup-rootfs

**argument**: `target` (default: `"rootfs"`)

This action sets up a writable emulation of the root filesystem that
the installer will run in at the directory named by `target`. Changes
to this rootfs will be present in the rootfs used by installer on the
modified ISO.

Many actions will do this implicitly but it may be clearer to be
explicit about the target directory name if later `shell` or `cp`
actions refer to paths in the rootfs.

### shell

**argument**: `command` (default: `null`)

Runs a shell (bash) in the main temporary directory. If `command` is
present, this is the command that is run. If not, an interactive shell
is run. If the shell (command or interactive) exits with a non-zero
code, that aborts the run.

### cp

**argument**: `source`

**argument**: `dest`

Copy a file. `dest` is assumed to be relative to the main temporary
directory. So something like this:

```
--cp /my/custom/initrd new/iso/casper/initrd
```

to replace the initrd.

### inject-snap

**argument**: `snap`

**argument**: `channel` (default: `"stable"`)

Inject the passed snap into the rootfs the installer runs in. This is
used to test new versions of subiquity. If there is an assert
alongside the snap, this will be copied into the ISO too and the snap
set up to track the passed channel, otherwise it is installed
unasserted.

### edit-squashfs

**argument**: `name`

**argument**: `add_sys_mounts` (default: `true`)

Mount the squashfs named `name` (most likely `"filesystem"`) at
`new/{name}` and arrange for it be repacked if there are any changes
before the new ISO is made.

`add_sys_mounts` controls whether the usual chroot setup stuff is done
(mounting /dev, /proc/ etc, setting up /etc/resolv.conf).

### add-cmdline-arg

**argument**: `arg`

**argument**: `persist` (default: `true`)

Add an argument to the default kernel command line. If `persist` is
true, it will be present on the default kernel command line of the
installed system as well.

### add-autoinstall-config

**argument**: `autoinstall_config`

Add the provided autoinstall config to the ISO so it is used by
default. This also adds "autoinstall" to the default kernel command
line.

`autoinstall_config` is the path to a YAML file which can contain
either the autoinstall config directly or a cloud-init user-data file
(in which case it can contain other configuration for the live
installer session, such as ssh keys to be used for the `installer`
user).

### add-debs-to-pool

**argument**: list of deb files

Add the passed deb files to the repository on the CD so that they are
available for installation while the installer is running, even if the
install is done offline.

This will generate a new Ed25519 GPG key, sign the package repository
on the ISO with it, arrange for the public part to end up in
`/etc/apt/trusted.gpg.d/custom-iso-key.gpg` in the installed system,
and then throw the private part away. You should be aware of this
change to the default apt configuration! Deleting this file in an
autoinstall `late-command` would be a reasonable thing to do, unless
you want the option of using the ISO as an apt repository later on.

### add-packages-to-pool

**argument**: list of package names

This is a wrapper around `add-debs-to-pool` which takes package names
rather than deb files. It downloads the listed packages and any others
needed to satisfy their dependencies from the main Ubuntu archive and
passes them to `add-debs-to-pool`. Do read the note about GPG in the
description of that action.

### unpack-initrd

**argument**: `target` (default: `"new/initrd"`)

Unpack the initrd using unmkinitramfs into `target` (contents will
likely end up in subdirectories called things like `early`, `early2`
and `main`, at least on amd64) and arrange for these to be repacked
into a replacement initrd for the modified ISO if any changes are made.
