#!/bin/bash
# ============================================================================
# MintyHost — One-Click Windows 10 LXD Image Builder
# ============================================================================
# Fully automated: downloads Windows 10, installs it unattended as an LXD VM
# image, and publishes it so the panel can deploy Windows VPS instances.
#
# Usage:  bash setup_windows_image.sh
#    or:  bash setup_windows_image.sh /path/to/existing/Win10.iso
# ============================================================================
set -euo pipefail

WORK_DIR="/tmp/mintyhost-win10"
WIN_ISO="$WORK_DIR/Win10.iso"
VIRTIO_URL="https://fedorapeople.org/groups/virt/virtio-win/direct-downloads/stable-virtio/virtio-win.iso"
VIRTIO_ISO="$WORK_DIR/virtio-win.iso"
UNATTEND_DIR="$WORK_DIR/unattend"
UNATTEND_ISO="$WORK_DIR/unattend.iso"
VM_NAME="win10-builder"
ALIAS_NAME="windows/10"
LXC="/snap/bin/lxc"

# ── Colors ──
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

log()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
fail() { echo -e "${RED}[✗]${NC} $1"; exit 1; }
info() { echo -e "${CYAN}[→]${NC} $1"; }

echo ""
echo -e "${BOLD}============================================================${NC}"
echo -e "${BOLD}  MintyHost — One-Click Windows 10 Image Builder${NC}"
echo -e "${BOLD}============================================================${NC}"
echo ""

# ── Check root ──
if [ "$(id -u)" -ne 0 ]; then
    fail "This script must be run as root. Use: sudo bash $0"
fi

# ── Check LXD ──
if ! command -v $LXC &>/dev/null; then
    fail "LXD not found. Install with: sudo snap install lxd && sudo lxd init --auto"
fi

# ── Install dependencies ──
info "Installing required tools (genisoimage, wget, curl)..."
apt-get install -y genisoimage wget curl jq >/dev/null 2>&1 || {
    warn "Some packages may not have installed. Continuing..."
}

# ── Check if image already exists ──
if $LXC image list --format=json 2>/dev/null | grep -q "\"$ALIAS_NAME\""; then
    warn "Image '$ALIAS_NAME' already exists. Deleting old image..."
    $LXC image delete "$ALIAS_NAME" 2>/dev/null || true
fi

# ── Clean up any previous builder VM ──
$LXC delete "$VM_NAME" --force 2>/dev/null || true

mkdir -p "$WORK_DIR" "$UNATTEND_DIR"

# ══════════════════════════════════════════════════════════════
# STEP 1: Get Windows 10 ISO
# ══════════════════════════════════════════════════════════════
if [ -n "${1:-}" ] && [ -f "${1:-}" ]; then
    log "Using provided ISO: $1"
    WIN_ISO="$1"
elif [ -f "$WIN_ISO" ]; then
    log "Found previously downloaded ISO at $WIN_ISO"
else
    info "Downloading Windows 10 ISO from Microsoft (~5.8 GB)..."
    info "This will take a while depending on your connection speed."
    echo ""

    ISO_URL=""
    UA="Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0"

    # ── Method 1: Microsoft Software Download API ──
    info "Trying Microsoft download API..."
    SESSION_ID=$(cat /proc/sys/kernel/random/uuid 2>/dev/null || echo "auto-$(date +%s)")

    SKU_RESPONSE=$(curl -sS --max-time 30 \
        "https://www.microsoft.com/en-us/api/controls/contentinclude/html?pageId=a8f8f489-4c7f-463a-9ca6-5cff94d8d041&host=www.microsoft.com&segments=software-download,windows10ISO&query=&action=getskuinformationbyproductedition&sessionId=${SESSION_ID}&productEditionId=2618&sdVersion=2" \
        -A "$UA" \
        -H "Referer: https://www.microsoft.com/en-us/software-download/windows10ISO" \
        2>/dev/null) || true

    # Extract the first SKU ID (English)
    SKU_ID=""
    if [ -n "$SKU_RESPONSE" ]; then
        # Try JSON-style extraction
        SKU_ID=$(echo "$SKU_RESPONSE" | grep -oP '"id"\s*:\s*\K[0-9]+' 2>/dev/null | head -1) || true
        # Try option value extraction
        if [ -z "$SKU_ID" ]; then
            SKU_ID=$(echo "$SKU_RESPONSE" | grep -oP 'value="(\K[0-9]+)' 2>/dev/null | head -1) || true
        fi
    fi

    if [ -n "$SKU_ID" ]; then
        info "Got SKU ID: $SKU_ID — requesting download links..."

        DL_RESPONSE=$(curl -sS --max-time 30 \
            "https://www.microsoft.com/en-us/api/controls/contentinclude/html?pageId=cfa9e580-a81e-4a4b-a846-7b21bf4e2e5b&host=www.microsoft.com&segments=software-download,windows10ISO&query=&action=GetProductDownloadLinksBySku&sessionId=${SESSION_ID}&skuId=${SKU_ID}&language=English&sdVersion=2" \
            -A "$UA" \
            -H "Referer: https://www.microsoft.com/en-us/software-download/windows10ISO" \
            2>/dev/null) || true

        if [ -n "$DL_RESPONSE" ]; then
            ISO_URL=$(echo "$DL_RESPONSE" | grep -oP 'href="(https://software[^"]*\.iso)"' 2>/dev/null | head -1 | sed 's/href="//;s/"//') || true
            if [ -z "$ISO_URL" ]; then
                ISO_URL=$(echo "$DL_RESPONSE" | grep -oP 'https://software[^"'\'']*\.iso' 2>/dev/null | head -1) || true
            fi
        fi
    fi

    # ── Method 2: Try evaluation center page scrape ──
    if [ -z "$ISO_URL" ]; then
        warn "Microsoft API did not return a download link."
        info "Trying Microsoft Evaluation Center..."
        EVAL_PAGE=$(curl -sS --max-time 30 -L \
            "https://www.microsoft.com/en-us/evalcenter/download-windows-10-enterprise" \
            -A "$UA" 2>/dev/null) || true

        if [ -n "$EVAL_PAGE" ]; then
            ISO_URL=$(echo "$EVAL_PAGE" | grep -oP 'https://[^"'\'']*64[^"'\'']*\.iso' 2>/dev/null | head -1) || true
        fi
    fi

    # ── Method 3: Fail with manual instructions ──
    if [ -z "$ISO_URL" ]; then
        echo ""
        echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        echo -e "${RED}  Auto-download failed (Microsoft may have changed their API)${NC}"
        echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        echo ""
        echo "  Please download Windows 10 manually:"
        echo ""
        echo "  1. On your PC, go to:"
        echo "     https://www.microsoft.com/en-us/software-download/windows10ISO"
        echo ""
        echo "  2. Download the 64-bit English ISO"
        echo ""
        echo "  3. Upload it to your server:"
        echo "     scp Win10*.iso root@YOUR_SERVER:$WIN_ISO"
        echo ""
        echo "  4. Re-run this script:"
        echo "     bash $0 $WIN_ISO"
        echo ""
        exit 1
    fi

    log "Download URL found! Starting download..."
    echo ""
    wget --progress=bar:force:noscroll -O "$WIN_ISO" "$ISO_URL" || {
        rm -f "$WIN_ISO"
        fail "Download failed. Try downloading manually and re-running:\n  bash $0 /path/to/Win10.iso"
    }
    echo ""
    log "Windows 10 ISO downloaded successfully!"
fi

# ══════════════════════════════════════════════════════════════
# STEP 2: Download VirtIO drivers
# ══════════════════════════════════════════════════════════════
if [ -f "$VIRTIO_ISO" ]; then
    log "VirtIO drivers already downloaded."
else
    info "Downloading VirtIO drivers (~500 MB)..."
    wget --progress=bar:force:noscroll -O "$VIRTIO_ISO" "$VIRTIO_URL" || fail "VirtIO download failed!"
    echo ""
    log "VirtIO drivers downloaded!"
fi

# ══════════════════════════════════════════════════════════════
# STEP 3: Create unattended installation config
# ══════════════════════════════════════════════════════════════
info "Creating unattended installation config..."

cat > "$UNATTEND_DIR/autounattend.xml" << 'XMLEOF'
<?xml version="1.0" encoding="utf-8"?>
<unattend xmlns="urn:schemas-microsoft-com:unattend" xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State">

    <!-- ═══ Windows PE: disk setup + driver loading ═══ -->
    <settings pass="windowsPE">
        <component name="Microsoft-Windows-International-Core-WinPE" processorArchitecture="amd64"
                   publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS">
            <SetupUILanguage><UILanguage>en-US</UILanguage></SetupUILanguage>
            <InputLocale>en-US</InputLocale>
            <SystemLocale>en-US</SystemLocale>
            <UILanguage>en-US</UILanguage>
            <UserLocale>en-US</UserLocale>
        </component>

        <!-- Load VirtIO storage drivers so Windows PE can see the virtual disk -->
        <component name="Microsoft-Windows-PnpCustomizationsWinPE" processorArchitecture="amd64"
                   publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS">
            <DriverPaths>
                <PathAndCredentials wcm:action="add" wcm:keyValue="1"><Path>D:\vioscsi\w10\amd64</Path></PathAndCredentials>
                <PathAndCredentials wcm:action="add" wcm:keyValue="2"><Path>E:\vioscsi\w10\amd64</Path></PathAndCredentials>
                <PathAndCredentials wcm:action="add" wcm:keyValue="3"><Path>F:\vioscsi\w10\amd64</Path></PathAndCredentials>
                <PathAndCredentials wcm:action="add" wcm:keyValue="4"><Path>D:\viostor\w10\amd64</Path></PathAndCredentials>
                <PathAndCredentials wcm:action="add" wcm:keyValue="5"><Path>E:\viostor\w10\amd64</Path></PathAndCredentials>
                <PathAndCredentials wcm:action="add" wcm:keyValue="6"><Path>F:\viostor\w10\amd64</Path></PathAndCredentials>
            </DriverPaths>
        </component>

        <!-- Partition + install target -->
        <component name="Microsoft-Windows-Setup" processorArchitecture="amd64"
                   publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS">
            <DiskConfiguration>
                <Disk wcm:action="add">
                    <DiskID>0</DiskID>
                    <WillWipeDisk>true</WillWipeDisk>
                    <CreatePartitions>
                        <CreatePartition wcm:action="add"><Order>1</Order><Type>EFI</Type><Size>512</Size></CreatePartition>
                        <CreatePartition wcm:action="add"><Order>2</Order><Type>MSR</Type><Size>128</Size></CreatePartition>
                        <CreatePartition wcm:action="add"><Order>3</Order><Type>Primary</Type><Extend>true</Extend></CreatePartition>
                    </CreatePartitions>
                    <ModifyPartitions>
                        <ModifyPartition wcm:action="add"><Order>1</Order><PartitionID>1</PartitionID><Format>FAT32</Format><Label>EFI</Label></ModifyPartition>
                        <ModifyPartition wcm:action="add"><Order>2</Order><PartitionID>2</PartitionID></ModifyPartition>
                        <ModifyPartition wcm:action="add"><Order>3</Order><PartitionID>3</PartitionID><Format>NTFS</Format><Label>Windows</Label><Letter>C</Letter></ModifyPartition>
                    </ModifyPartitions>
                </Disk>
            </DiskConfiguration>
            <ImageInstall>
                <OSImage>
                    <InstallFrom>
                        <MetaData wcm:action="add">
                            <Key>/IMAGE/INDEX</Key>
                            <Value>1</Value>
                        </MetaData>
                    </InstallFrom>
                    <InstallTo><DiskID>0</DiskID><PartitionID>3</PartitionID></InstallTo>
                </OSImage>
            </ImageInstall>
            <UserData>
                <AcceptEula>true</AcceptEula>
                <FullName>Admin</FullName>
                <Organization>MintyHost</Organization>
            </UserData>
        </component>
    </settings>

    <!-- ═══ Specialize: network drivers + RDP + hostname ═══ -->
    <settings pass="specialize">
        <component name="Microsoft-Windows-Shell-Setup" processorArchitecture="amd64"
                   publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS">
            <ComputerName>WIN-LXD</ComputerName>
            <TimeZone>UTC</TimeZone>
        </component>

        <!-- Load VirtIO network + balloon + display drivers -->
        <component name="Microsoft-Windows-PnpCustomizationsNonWinPE" processorArchitecture="amd64"
                   publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS">
            <DriverPaths>
                <PathAndCredentials wcm:action="add" wcm:keyValue="1"><Path>D:\NetKVM\w10\amd64</Path></PathAndCredentials>
                <PathAndCredentials wcm:action="add" wcm:keyValue="2"><Path>E:\NetKVM\w10\amd64</Path></PathAndCredentials>
                <PathAndCredentials wcm:action="add" wcm:keyValue="3"><Path>F:\NetKVM\w10\amd64</Path></PathAndCredentials>
                <PathAndCredentials wcm:action="add" wcm:keyValue="4"><Path>D:\Balloon\w10\amd64</Path></PathAndCredentials>
                <PathAndCredentials wcm:action="add" wcm:keyValue="5"><Path>E:\Balloon\w10\amd64</Path></PathAndCredentials>
                <PathAndCredentials wcm:action="add" wcm:keyValue="6"><Path>F:\Balloon\w10\amd64</Path></PathAndCredentials>
                <PathAndCredentials wcm:action="add" wcm:keyValue="7"><Path>D:\qxldod\w10\amd64</Path></PathAndCredentials>
                <PathAndCredentials wcm:action="add" wcm:keyValue="8"><Path>E:\qxldod\w10\amd64</Path></PathAndCredentials>
                <PathAndCredentials wcm:action="add" wcm:keyValue="9"><Path>F:\qxldod\w10\amd64</Path></PathAndCredentials>
                <PathAndCredentials wcm:action="add" wcm:keyValue="10"><Path>D:\vioserial\w10\amd64</Path></PathAndCredentials>
                <PathAndCredentials wcm:action="add" wcm:keyValue="11"><Path>E:\vioserial\w10\amd64</Path></PathAndCredentials>
            </DriverPaths>
        </component>

        <!-- Enable Remote Desktop -->
        <component name="Microsoft-Windows-TerminalServices-LocalSessionManager" processorArchitecture="amd64"
                   publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS">
            <fDenyTSConnections>false</fDenyTSConnections>
        </component>
        <component name="Networking-MPSSVC-Svc" processorArchitecture="amd64"
                   publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS">
            <FirewallGroups>
                <FirewallGroup wcm:action="add" wcm:keyValue="RemoteDesktop">
                    <Active>true</Active>
                    <Group>Remote Desktop</Group>
                    <Profile>all</Profile>
                </FirewallGroup>
            </FirewallGroups>
        </component>
    </settings>

    <!-- ═══ OOBE: skip all prompts, create admin, shutdown when done ═══ -->
    <settings pass="oobeSystem">
        <component name="Microsoft-Windows-Shell-Setup" processorArchitecture="amd64"
                   publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS">
            <OOBE>
                <HideEULAPage>true</HideEULAPage>
                <HideLocalAccountScreen>true</HideLocalAccountScreen>
                <HideOEMRegistrationScreen>true</HideOEMRegistrationScreen>
                <HideOnlineAccountScreens>true</HideOnlineAccountScreens>
                <HideWirelessSetupInOOBE>true</HideWirelessSetupInOOBE>
                <ProtectYourPC>3</ProtectYourPC>
            </OOBE>

            <UserAccounts>
                <AdministratorPassword>
                    <Value>admin123</Value>
                    <PlainText>true</PlainText>
                </AdministratorPassword>
                <LocalAccounts>
                    <LocalAccount wcm:action="add">
                        <Password><Value>admin123</Value><PlainText>true</PlainText></Password>
                        <DisplayName>Admin</DisplayName>
                        <Name>Admin</Name>
                        <Group>Administrators</Group>
                    </LocalAccount>
                </LocalAccounts>
            </UserAccounts>

            <!-- Auto-logon once to run FirstLogonCommands, then shutdown -->
            <AutoLogon>
                <Enabled>true</Enabled>
                <Username>Admin</Username>
                <Password><Value>admin123</Value><PlainText>true</PlainText></Password>
                <LogonCount>1</LogonCount>
            </AutoLogon>

            <FirstLogonCommands>
                <!-- Enable RDP via registry -->
                <SynchronousCommand wcm:action="add">
                    <Order>1</Order>
                    <CommandLine>cmd /c reg add "HKLM\SYSTEM\CurrentControlSet\Control\Terminal Server" /v fDenyTSConnections /t REG_DWORD /d 0 /f</CommandLine>
                    <RequiresUserInput>false</RequiresUserInput>
                </SynchronousCommand>
                <!-- Open RDP firewall port -->
                <SynchronousCommand wcm:action="add">
                    <Order>2</Order>
                    <CommandLine>cmd /c netsh advfirewall firewall add rule name="Allow RDP" dir=in protocol=tcp localport=3389 action=allow</CommandLine>
                    <RequiresUserInput>false</RequiresUserInput>
                </SynchronousCommand>
                <!-- Enable OpenSSH Server if available -->
                <SynchronousCommand wcm:action="add">
                    <Order>3</Order>
                    <CommandLine>powershell -Command "Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0; Set-Service sshd -StartupType Automatic; Start-Service sshd" </CommandLine>
                    <RequiresUserInput>false</RequiresUserInput>
                </SynchronousCommand>
                <!-- Disable auto-logon -->
                <SynchronousCommand wcm:action="add">
                    <Order>4</Order>
                    <CommandLine>cmd /c reg add "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon" /v AutoAdminLogon /t REG_SZ /d 0 /f</CommandLine>
                    <RequiresUserInput>false</RequiresUserInput>
                </SynchronousCommand>
                <!-- Shutdown to signal the builder script that installation is done -->
                <SynchronousCommand wcm:action="add">
                    <Order>5</Order>
                    <CommandLine>shutdown /s /t 10 /c "MintyHost: Windows image setup complete."</CommandLine>
                    <RequiresUserInput>false</RequiresUserInput>
                </SynchronousCommand>
            </FirstLogonCommands>
        </component>
    </settings>
</unattend>
XMLEOF

log "Unattended config created."

# ── Package autounattend.xml into an ISO ──
info "Building unattend ISO..."
genisoimage -quiet -o "$UNATTEND_ISO" -J -r "$UNATTEND_DIR/" 2>/dev/null
log "Unattend ISO ready."

# ══════════════════════════════════════════════════════════════
# STEP 4: Create the LXD VM
# ══════════════════════════════════════════════════════════════
info "Creating empty LXD virtual machine: $VM_NAME ..."

$LXC init "$VM_NAME" --empty --vm \
    -c limits.cpu=2 \
    -c limits.memory=4GB \
    -c security.secureboot=false

# Set root disk to 40GB
$LXC config device override "$VM_NAME" root size=40GB

# Attach Windows installation ISO (boot priority = highest)
$LXC config device add "$VM_NAME" win-iso disk source="$WIN_ISO" boot.priority=10

# Attach VirtIO drivers ISO
$LXC config device add "$VM_NAME" virtio-iso disk source="$VIRTIO_ISO"

# Attach autounattend ISO (Windows PE auto-scans all drives for autounattend.xml)
$LXC config device add "$VM_NAME" unattend-iso disk source="$UNATTEND_ISO"

log "VM created with all ISOs attached."

# ══════════════════════════════════════════════════════════════
# STEP 5: Start VM and wait for unattended installation
# ══════════════════════════════════════════════════════════════
info "Starting VM — Windows installation will run automatically..."
$LXC start "$VM_NAME"

echo ""
echo -e "${BOLD}┌──────────────────────────────────────────────────────────┐${NC}"
echo -e "${BOLD}│  Windows is installing automatically (no action needed)  │${NC}"
echo -e "${BOLD}│  This typically takes 20-40 minutes. Please wait...      │${NC}"
echo -e "${BOLD}└──────────────────────────────────────────────────────────┘${NC}"
echo ""

# Wait up to 60 minutes for installation to complete
# The autounattend.xml will shut down the VM when done
MAX_WAIT=120  # 120 * 30s = 60 minutes
COMPLETED=false

for i in $(seq 1 $MAX_WAIT); do
    sleep 30
    STATUS=$($LXC info "$VM_NAME" 2>/dev/null | grep "^Status:" | awk '{print tolower($2)}') || true

    ELAPSED_MIN=$(( i * 30 / 60 ))

    if [ "$STATUS" = "stopped" ]; then
        echo ""
        log "VM has shut down — Windows installation complete! (${ELAPSED_MIN} min)"
        COMPLETED=true
        break
    fi

    # Progress indicator
    if (( i % 2 == 0 )); then
        echo -e "  ${CYAN}⏳${NC} Still installing... (${ELAPSED_MIN} minutes elapsed)"
    fi
done

if [ "$COMPLETED" = false ]; then
    warn "Installation did not complete within 60 minutes."
    warn "The VM may still be running. You can check with: $LXC info $VM_NAME"
    warn "Once it's stopped, run the publish step manually:"
    echo "  $LXC config device remove $VM_NAME win-iso"
    echo "  $LXC config device remove $VM_NAME virtio-iso"
    echo "  $LXC config device remove $VM_NAME unattend-iso"
    echo "  $LXC publish $VM_NAME --alias $ALIAS_NAME description=\"Windows 10 Pro VM\""
    echo "  $LXC delete $VM_NAME --force"
    exit 1
fi

# ══════════════════════════════════════════════════════════════
# STEP 6: Clean up ISOs and publish image
# ══════════════════════════════════════════════════════════════
info "Removing ISO devices from VM..."
$LXC config device remove "$VM_NAME" win-iso 2>/dev/null || true
$LXC config device remove "$VM_NAME" virtio-iso 2>/dev/null || true
$LXC config device remove "$VM_NAME" unattend-iso 2>/dev/null || true

info "Publishing VM as reusable image '$ALIAS_NAME'..."
info "(This may take 5-10 minutes as the disk image is compressed)"
$LXC publish "$VM_NAME" --alias "$ALIAS_NAME" description="Windows 10 Pro VM (MintyHost)" || {
    fail "Failed to publish image. The VM is still available as '$VM_NAME'."
}

log "Image published as '$ALIAS_NAME'!"

# ── Cleanup ──
info "Cleaning up builder VM and temp files..."
$LXC delete "$VM_NAME" --force 2>/dev/null || true
rm -rf "$UNATTEND_DIR" "$UNATTEND_ISO"
# Keep the ISOs in case they're needed later
# rm -f "$WIN_ISO" "$VIRTIO_ISO"

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  ✅ SUCCESS! Windows 10 image is ready!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "  You can now deploy Windows VPS from the MintyHost panel."
echo "  The image is available as: $ALIAS_NAME"
echo ""
echo "  Verify with:  $LXC image list | grep windows"
echo ""
echo "  Note: Windows VMs need at least 2 vCPU, 4GB RAM, 40GB disk."
echo "  Downloaded ISOs are kept at: $WORK_DIR/"
echo ""
