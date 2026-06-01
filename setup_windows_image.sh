#!/bin/bash
# ============================================================================
# MintyHost — Windows 10 VM Image Setup for LXD
# ============================================================================
# This script helps you import a Windows 10 ISO as a launchable LXD VM image.
#
# PREREQUISITES:
#   1. An LXD installation (snap install lxd)  
#   2. A Windows 10 ISO file (download from microsoft.com)
#   3. VirtIO drivers ISO (downloaded automatically by this script)
#   4. At least 40GB free disk space
#
# USAGE:
#   bash setup_windows_image.sh /path/to/windows10.iso
# ============================================================================
set -e

WINDOWS_ISO="${1}"
VIRTIO_URL="https://fedorapeople.org/groups/virt/virtio-win/direct-downloads/stable-virtio/virtio-win.iso"
VIRTIO_ISO="/tmp/virtio-win.iso"
VM_NAME="win10-setup"
ALIAS_NAME="windows/10"

echo "============================================================"
echo "  MintyHost — Windows 10 VM Image Setup"
echo "============================================================"

# ── Validate ISO path ──
if [ -z "$WINDOWS_ISO" ] || [ ! -f "$WINDOWS_ISO" ]; then
    echo ""
    echo "ERROR: Please provide a valid path to a Windows 10 ISO file."
    echo ""
    echo "Usage:  bash $0 /path/to/Win10_22H2_English_x64v1.iso"
    echo ""
    echo "You can download Windows 10 ISO from:"
    echo "  https://www.microsoft.com/en-us/software-download/windows10ISO"
    echo ""
    exit 1
fi

echo ""
echo "[1/6] Checking LXD VM support..."
if ! /snap/bin/lxc info | grep -q "driver_version"; then
    echo "ERROR: LXD does not appear to be properly initialized."
    echo "Run: sudo lxd init --auto"
    exit 1
fi

echo "[2/6] Downloading VirtIO drivers ISO (required for Windows VMs)..."
if [ -f "$VIRTIO_ISO" ]; then
    echo "  → VirtIO ISO already exists at $VIRTIO_ISO, skipping download."
else
    echo "  → Downloading from $VIRTIO_URL ..."
    curl -Lo "$VIRTIO_ISO" "$VIRTIO_URL"
fi

echo "[3/6] Creating empty LXD VM: $VM_NAME ..."
# Delete any existing setup VM
/snap/bin/lxc delete "$VM_NAME" --force 2>/dev/null || true

# Create an empty VM with enough resources for Windows installation
/snap/bin/lxc init "$VM_NAME" --empty --vm \
    -c limits.cpu=2 \
    -c limits.memory=4GB \
    -c security.secureboot=false

# Configure root disk size (40GB)
/snap/bin/lxc config device override "$VM_NAME" root size=40GB

echo "[4/6] Attaching ISO files to VM..."
# Attach Windows ISO as install media
/snap/bin/lxc config device add "$VM_NAME" win-iso disk source="$WINDOWS_ISO" boot.priority=10

# Attach VirtIO drivers ISO 
/snap/bin/lxc config device add "$VM_NAME" virtio-iso disk source="$VIRTIO_ISO"

echo "[5/6] Starting VM for Windows installation..."
/snap/bin/lxc start "$VM_NAME"

echo ""
echo "============================================================"
echo "  VM is now booting from the Windows ISO!"
echo "============================================================"
echo ""
echo "NEXT STEPS:"
echo ""
echo "  1. Connect to the VM console to complete Windows installation:"
echo "     /snap/bin/lxc console $VM_NAME --type=vga"
echo ""
echo "  2. During Windows Setup, when asked 'Where do you want to install',"
echo "     click 'Load driver' and browse the VirtIO CD for the storage"
echo "     driver (vioscsi\\w10\\amd64)."
echo ""
echo "  3. Complete Windows installation normally."
echo ""
echo "  4. After Windows is installed and booted, install the VirtIO"
echo "     network driver from the VirtIO CD (NetKVM\\w10\\amd64)."
echo ""
echo "  5. Shut down Windows cleanly from inside the VM."
echo ""
echo "  6. Once the VM is stopped, remove the ISO devices:"
echo "     /snap/bin/lxc config device remove $VM_NAME win-iso"
echo "     /snap/bin/lxc config device remove $VM_NAME virtio-iso"
echo ""
echo "  7. Publish the VM as a reusable image:"
echo "     /snap/bin/lxc publish $VM_NAME --alias $ALIAS_NAME \\"
echo "       --public description=\"Windows 10 Pro VM\""
echo ""
echo "  8. (Optional) Delete the setup VM:"
echo "     /snap/bin/lxc delete $VM_NAME"
echo ""
echo "  9. You can now deploy Windows VPS from the MintyHost panel!"
echo ""
echo "============================================================"
echo ""
echo "[6/6] Waiting for you to complete the installation..."
echo "  Run '/snap/bin/lxc console $VM_NAME --type=vga' in another terminal."
echo ""
