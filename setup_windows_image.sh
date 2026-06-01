#!/bin/bash
# ============================================================================
# MintyHost — One-Click Windows 10 LXD Image Builder
# ============================================================================
# Fully automated: downloads Windows 10 via UUP dump (Microsoft Update CDN),
# installs it unattended in an LXD VM, and publishes it as a reusable image.
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

[ "$(id -u)" -ne 0 ] && fail "Run as root: sudo bash $0"
command -v $LXC &>/dev/null || fail "LXD not found. Install: sudo snap install lxd && sudo lxd init --auto"

# ── Install all dependencies ──
info "Installing required tools..."
apt-get update -qq >/dev/null 2>&1
apt-get install -y -qq aria2 wimtools cabextract chntpw genisoimage wget curl jq git >/dev/null 2>&1 || {
    warn "Some packages may not have installed via apt. Trying individual installs..."
    for pkg in aria2 wimtools cabextract chntpw genisoimage wget curl jq git; do
        apt-get install -y -qq "$pkg" >/dev/null 2>&1 || warn "Could not install: $pkg"
    done
}
log "Dependencies ready."

# ── Check / clean existing image & builder VM ──
if $LXC image list --format=json 2>/dev/null | grep -q "\"$ALIAS_NAME\""; then
    warn "Image '$ALIAS_NAME' already exists — will overwrite after new build."
fi
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
    info "Downloading Windows 10 from Microsoft Update servers via UUP dump..."
    echo ""

    # ── Query UUP dump API for latest Windows 10 22H2 build ──
    info "Querying UUP dump for latest Windows 10 22H2 build..."
    API_RESPONSE=$(curl -sS --max-time 30 "https://api.uupdump.net/listid.php?search=19045&sortByDate=1" 2>/dev/null) || true

    BUILD_UUID=""
    BUILD_TITLE=""
    if [ -n "$API_RESPONSE" ]; then
        BUILD_UUID=$(echo "$API_RESPONSE" | jq -r '
            [.response.builds | to_entries[] |
             select(.value.title | test("Windows 10"; "i")) |
             select(.value.title | test("amd64|x64"; "i"))
            ][0].key // empty' 2>/dev/null) || true

        if [ -z "$BUILD_UUID" ]; then
            BUILD_UUID=$(echo "$API_RESPONSE" | jq -r '
                [.response.builds | to_entries[]
                ][0].key // empty' 2>/dev/null) || true
        fi

        if [ -n "$BUILD_UUID" ]; then
            BUILD_TITLE=$(echo "$API_RESPONSE" | jq -r ".response.builds[\"$BUILD_UUID\"].title // \"Unknown\"" 2>/dev/null) || true
        fi
    fi

    if [ -z "$BUILD_UUID" ] || [ "$BUILD_UUID" = "null" ]; then
        fail "Could not find Windows 10 build on UUP dump API.\nPlease download a Windows 10 ISO manually and run:\n  sudo bash $0 /path/to/Win10.iso"
    fi

    log "Found: $BUILD_TITLE"
    log "Build ID: $BUILD_UUID"

    # ── Get download URLs from UUP dump ──
    info "Fetching file list from Microsoft CDN..."
    FILES_JSON=$(curl -sS --max-time 30 "https://api.uupdump.net/get.php?id=${BUILD_UUID}&lang=en-us&edition=professional" 2>/dev/null) || true

    # Check for errors
    API_ERROR=$(echo "$FILES_JSON" | jq -r '.response.error // empty' 2>/dev/null) || true
    if [ -n "$API_ERROR" ]; then
        warn "UUP dump API error: $API_ERROR"
        info "Trying without edition filter..."
        FILES_JSON=$(curl -sS --max-time 30 "https://api.uupdump.net/get.php?id=${BUILD_UUID}&lang=en-us" 2>/dev/null) || true
    fi

    if [ -z "$FILES_JSON" ]; then
        fail "Could not get download URLs from UUP dump."
    fi

    # ── Build aria2 download list ──
    UUP_DIR="$WORK_DIR/uup-files"
    mkdir -p "$UUP_DIR"

    echo "$FILES_JSON" | jq -r '
        .response.files | to_entries[] |
        .value.url + "\n  out=" + .key + "\n  checksum=sha-1=" + .value.sha1
    ' > "$WORK_DIR/uup-urls.txt" 2>/dev/null || true

    NUM_FILES=$(grep -c "^http" "$WORK_DIR/uup-urls.txt" 2>/dev/null || echo "0")

    if [ "$NUM_FILES" -eq 0 ]; then
        fail "No download URLs found from UUP dump. API may have changed.\nPlease download a Windows 10 ISO manually and run:\n  sudo bash $0 /path/to/Win10.iso"
    fi

    log "Downloading $NUM_FILES files from Microsoft CDN..."
    info "This is ~4-5 GB and may take 10-30 minutes..."
    echo ""

    aria2c --input-file="$WORK_DIR/uup-urls.txt" \
        --dir="$UUP_DIR" \
        --max-concurrent-downloads=5 \
        --max-connection-per-server=5 \
        --min-split-size=5M \
        --check-integrity=true \
        --continue=true \
        --summary-interval=60 \
        --console-log-level=warn \
        --download-result=hide || {
        fail "Download failed. Check your internet connection and try again."
    }

    echo ""
    log "All UUP files downloaded!"

    # ── Clone UUP dump converter and build ISO ──
    info "Building Windows 10 ISO from downloaded files (this takes 5-15 min)..."
    CONVERTER_DIR="$WORK_DIR/converter"

    if [ ! -d "$CONVERTER_DIR/.git" ]; then
        rm -rf "$CONVERTER_DIR"
        git clone --depth=1 https://git.uupdump.net/uupdump/converter.git "$CONVERTER_DIR" 2>/dev/null || {
            # Fallback mirror
            warn "Primary converter repo unavailable, trying GitHub mirror..."
            git clone --depth=1 https://github.com/AveYo/MediaCreationTool.bat.git "$CONVERTER_DIR" 2>/dev/null || {
                fail "Could not download UUP converter. Try downloading a Windows ISO manually."
            }
        }
    fi

    cd "$CONVERTER_DIR"
    chmod +x convert.sh 2>/dev/null || true

    # Run the converter
    if [ -f "convert.sh" ]; then
        bash convert.sh wim "$UUP_DIR" 0 1 2>&1 | tail -20
    else
        fail "Converter script not found in $CONVERTER_DIR"
    fi

    # Find the generated ISO
    GENERATED_ISO=$(find "$CONVERTER_DIR" -maxdepth 1 -name "*.iso" -type f 2>/dev/null | head -1)
    if [ -z "$GENERATED_ISO" ]; then
        GENERATED_ISO=$(find "$WORK_DIR" -name "*.iso" -newer "$WORK_DIR/uup-urls.txt" -type f 2>/dev/null | grep -iv virtio | head -1)
    fi

    if [ -z "$GENERATED_ISO" ]; then
        fail "ISO generation failed. No ISO file was created.\nTry downloading a Windows 10 ISO manually and run:\n  sudo bash $0 /path/to/Win10.iso"
    fi

    mv "$GENERATED_ISO" "$WIN_ISO"
    log "Windows 10 ISO created: $WIN_ISO ($(du -h "$WIN_ISO" | cut -f1))"
    cd /tmp
fi

# Verify ISO exists and is reasonable size (> 2GB)
if [ ! -f "$WIN_ISO" ]; then
    fail "Windows ISO not found at $WIN_ISO"
fi
ISO_SIZE=$(stat -c%s "$WIN_ISO" 2>/dev/null || echo "0")
if [ "$ISO_SIZE" -lt 2000000000 ]; then
    warn "ISO file seems small ($(du -h "$WIN_ISO" | cut -f1)). It may be corrupted."
fi

# ══════════════════════════════════════════════════════════════
# STEP 2: Download VirtIO drivers
# ══════════════════════════════════════════════════════════════
if [ -f "$VIRTIO_ISO" ]; then
    log "VirtIO drivers already downloaded."
else
    info "Downloading VirtIO drivers (~500 MB)..."
    wget -q --show-progress -O "$VIRTIO_ISO" "$VIRTIO_URL" || fail "VirtIO download failed!"
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

    <settings pass="windowsPE">
        <component name="Microsoft-Windows-International-Core-WinPE" processorArchitecture="amd64"
                   publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS">
            <SetupUILanguage><UILanguage>en-US</UILanguage></SetupUILanguage>
            <InputLocale>en-US</InputLocale>
            <SystemLocale>en-US</SystemLocale>
            <UILanguage>en-US</UILanguage>
            <UserLocale>en-US</UserLocale>
        </component>

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

    <settings pass="specialize">
        <component name="Microsoft-Windows-Shell-Setup" processorArchitecture="amd64"
                   publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS">
            <ComputerName>WIN-LXD</ComputerName>
            <TimeZone>UTC</TimeZone>
        </component>
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
                <PathAndCredentials wcm:action="add" wcm:keyValue="9"><Path>D:\vioserial\w10\amd64</Path></PathAndCredentials>
                <PathAndCredentials wcm:action="add" wcm:keyValue="10"><Path>E:\vioserial\w10\amd64</Path></PathAndCredentials>
            </DriverPaths>
        </component>
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
            <AutoLogon>
                <Enabled>true</Enabled>
                <Username>Admin</Username>
                <Password><Value>admin123</Value><PlainText>true</PlainText></Password>
                <LogonCount>1</LogonCount>
            </AutoLogon>
            <FirstLogonCommands>
                <SynchronousCommand wcm:action="add">
                    <Order>1</Order>
                    <CommandLine>cmd /c reg add "HKLM\SYSTEM\CurrentControlSet\Control\Terminal Server" /v fDenyTSConnections /t REG_DWORD /d 0 /f</CommandLine>
                    <RequiresUserInput>false</RequiresUserInput>
                </SynchronousCommand>
                <SynchronousCommand wcm:action="add">
                    <Order>2</Order>
                    <CommandLine>cmd /c netsh advfirewall firewall add rule name="Allow RDP" dir=in protocol=tcp localport=3389 action=allow</CommandLine>
                    <RequiresUserInput>false</RequiresUserInput>
                </SynchronousCommand>
                <SynchronousCommand wcm:action="add">
                    <Order>3</Order>
                    <CommandLine>powershell -Command "Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0; Set-Service sshd -StartupType Automatic; Start-Service sshd" </CommandLine>
                    <RequiresUserInput>false</RequiresUserInput>
                </SynchronousCommand>
                <SynchronousCommand wcm:action="add">
                    <Order>4</Order>
                    <CommandLine>cmd /c reg add "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon" /v AutoAdminLogon /t REG_SZ /d 0 /f</CommandLine>
                    <RequiresUserInput>false</RequiresUserInput>
                </SynchronousCommand>
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

info "Building unattend ISO..."
genisoimage -quiet -o "$UNATTEND_ISO" -J -r "$UNATTEND_DIR/" 2>/dev/null
log "Unattend ISO ready."

# ══════════════════════════════════════════════════════════════
# STEP 4: Create the LXD VM
# ══════════════════════════════════════════════════════════════
info "Creating LXD virtual machine: $VM_NAME ..."

$LXC init "$VM_NAME" --empty --vm \
    -c limits.cpu=2 \
    -c limits.memory=4GB \
    -c security.secureboot=false

$LXC config device override "$VM_NAME" root size=40GB
$LXC config device add "$VM_NAME" win-iso disk source="$WIN_ISO" boot.priority=10
$LXC config device add "$VM_NAME" virtio-iso disk source="$VIRTIO_ISO"
$LXC config device add "$VM_NAME" unattend-iso disk source="$UNATTEND_ISO"

log "VM created with ISOs attached."

# ══════════════════════════════════════════════════════════════
# STEP 5: Start VM and wait for unattended installation
# ══════════════════════════════════════════════════════════════
info "Starting VM — Windows will install automatically..."
$LXC start "$VM_NAME"

echo ""
echo -e "${BOLD}┌──────────────────────────────────────────────────────────┐${NC}"
echo -e "${BOLD}│  Windows is installing automatically (no action needed)  │${NC}"
echo -e "${BOLD}│  Estimated time: 20-40 minutes. Please wait...           │${NC}"
echo -e "${BOLD}└──────────────────────────────────────────────────────────┘${NC}"
echo ""

MAX_WAIT=120
COMPLETED=false

for i in $(seq 1 $MAX_WAIT); do
    sleep 30
    STATUS=$($LXC info "$VM_NAME" 2>/dev/null | grep "^Status:" | awk '{print tolower($2)}') || true
    ELAPSED_MIN=$(( i * 30 / 60 ))

    if [ "$STATUS" = "stopped" ]; then
        echo ""
        log "VM shut down — Windows installation complete! (${ELAPSED_MIN} min)"
        COMPLETED=true
        break
    fi

    if (( i % 2 == 0 )); then
        echo -e "  ${CYAN}⏳${NC} Installing... (${ELAPSED_MIN} minutes elapsed)"
    fi
done

if [ "$COMPLETED" = false ]; then
    warn "Installation did not complete within 60 minutes."
    echo "  The VM may still be running. Check: $LXC info $VM_NAME"
    echo "  Once stopped, publish manually:"
    echo "    $LXC config device remove $VM_NAME win-iso"
    echo "    $LXC config device remove $VM_NAME virtio-iso"
    echo "    $LXC config device remove $VM_NAME unattend-iso"
    echo "    $LXC publish $VM_NAME --alias $ALIAS_NAME description=\"Windows 10 Pro VM\""
    echo "    $LXC delete $VM_NAME --force"
    exit 1
fi

# ══════════════════════════════════════════════════════════════
# STEP 6: Publish image
# ══════════════════════════════════════════════════════════════
info "Removing ISO devices..."
$LXC config device remove "$VM_NAME" win-iso 2>/dev/null || true
$LXC config device remove "$VM_NAME" virtio-iso 2>/dev/null || true
$LXC config device remove "$VM_NAME" unattend-iso 2>/dev/null || true

# Delete old image if exists
$LXC image delete "$ALIAS_NAME" 2>/dev/null || true

info "Publishing image as '$ALIAS_NAME' (may take 5-10 min)..."
$LXC publish "$VM_NAME" --alias "$ALIAS_NAME" description="Windows 10 Pro VM (MintyHost)" || {
    fail "Failed to publish. VM '$VM_NAME' still available for manual publish."
}

log "Image published!"

$LXC delete "$VM_NAME" --force 2>/dev/null || true
rm -rf "$UNATTEND_DIR" "$UNATTEND_ISO"

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  ✅ SUCCESS! Windows 10 image is ready!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "  Deploy Windows VPS from the MintyHost panel now!"
echo "  Image alias: $ALIAS_NAME"
echo "  Verify: $LXC image list | grep windows"
echo ""
echo "  Note: Windows VMs need at least 2 vCPU, 4GB RAM, 40GB disk."
echo ""
