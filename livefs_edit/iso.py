from .mount import add_mount, add_overlay, add_sys_mount


def setup_iso(isopath):
    add_mount('iso9660', isopath, 'old_iso', options='loop,ro')
    add_mount(
        'squashfs', 'old_iso/casper/filesystem.squashfs', 'old_filesystem')
    add_mount(
        'squashfs', 'old_iso/casper/installer.squashfs', 'old_installer')
    add_overlay('old_filesystem:old_installer', 'tree', upper='new_jnstaller')
    add_sys_mount('devtmpfs', 'tree/dev')
    add_sys_mount('devpts', 'tree/dev/pts')
    add_sys_mount('proc', 'tree/proc')
    add_sys_mount('sysfs', 'tree/sys')
    add_sys_mount('securityfs', 'tree/sys/kernel/security')
