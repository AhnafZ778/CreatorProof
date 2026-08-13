// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

/// @notice Who may co-attest in the CreatorProof network, under which role, and who governs
///         that list.
/// @dev Membership is a permission structure, never a statement about ownership of a work.
///      Role codes are mirrored in `app.domain.platform.NETWORK_MEMBER_ROLE_CODES`; changing
///      one side without the other is a schema break.
contract CreatorProofMemberRegistry {
    uint8 public constant STATUS_UNKNOWN = 0;
    uint8 public constant STATUS_ACTIVE = 1;
    uint8 public constant STATUS_SUSPENDED = 2;
    uint8 public constant STATUS_OFFBOARDED = 3;

    uint8 public constant ROLE_PLATFORM = 1;
    uint8 public constant ROLE_CREATOR = 2;
    uint8 public constant ROLE_AGENCY = 3;
    uint8 public constant ROLE_BRAND = 4;
    uint8 public constant ROLE_MARKETPLACE = 5;
    uint8 public constant ROLE_REVIEWER = 6;
    uint8 public constant ROLE_REGULATOR_OBSERVER = 7;

    string public constant SCOPE =
        "Membership and permission only. This registry does not assert authorship, ownership or licensing authority.";

    struct Member {
        bytes32 orgId;
        uint8 role;
        uint8 status;
        uint64 enrolledAt;
        uint64 updatedAt;
    }

    address public governor;
    address public pendingGovernor;
    /// @notice Recorded so oversight provisioning is visible on chain rather than promised.
    address public regulatorObserver;
    uint256 public activeMemberCount;

    mapping(address => Member) private _members;
    address[] private _enrolled;

    event MemberEnrolled(address indexed account, bytes32 indexed orgId, uint8 role);
    event MemberStatusChanged(address indexed account, uint8 previousStatus, uint8 newStatus);
    event MemberRoleChanged(address indexed account, uint8 previousRole, uint8 newRole);
    event GovernanceTransferProposed(address indexed current, address indexed proposed);
    event GovernanceTransferred(address indexed previous, address indexed current);
    event RegulatorObserverChanged(address indexed previous, address indexed current);

    modifier onlyGovernor() {
        require(msg.sender == governor, "NOT_GOVERNOR");
        _;
    }

    constructor(address initialGovernor) {
        require(initialGovernor != address(0), "GOVERNOR_REQUIRED");
        governor = initialGovernor;
        emit GovernanceTransferred(address(0), initialGovernor);
    }

    /// @dev Two-step so a mistyped address cannot strand the registry.
    function proposeGovernanceTransfer(address proposed) external onlyGovernor {
        require(proposed != address(0), "GOVERNOR_REQUIRED");
        pendingGovernor = proposed;
        emit GovernanceTransferProposed(governor, proposed);
    }

    function acceptGovernance() external {
        require(msg.sender == pendingGovernor, "NOT_PENDING_GOVERNOR");
        address previous = governor;
        governor = pendingGovernor;
        pendingGovernor = address(0);
        emit GovernanceTransferred(previous, governor);
    }

    function setRegulatorObserver(address observer) external onlyGovernor {
        address previous = regulatorObserver;
        regulatorObserver = observer;
        emit RegulatorObserverChanged(previous, observer);
    }

    function enroll(address account, bytes32 orgId, uint8 role) external onlyGovernor {
        require(account != address(0), "ACCOUNT_REQUIRED");
        require(orgId != bytes32(0), "ORG_ID_REQUIRED");
        require(role >= ROLE_PLATFORM && role <= ROLE_REGULATOR_OBSERVER, "ROLE_UNKNOWN");
        Member storage member = _members[account];
        require(member.status != STATUS_ACTIVE, "ALREADY_ACTIVE");
        if (member.enrolledAt == 0) {
            member.enrolledAt = uint64(block.timestamp);
            _enrolled.push(account);
        }
        uint8 previousStatus = member.status;
        uint8 previousRole = member.role;
        member.orgId = orgId;
        member.role = role;
        member.status = STATUS_ACTIVE;
        member.updatedAt = uint64(block.timestamp);
        activeMemberCount += 1;
        emit MemberEnrolled(account, orgId, role);
        if (previousRole != role) {
            emit MemberRoleChanged(account, previousRole, role);
        }
        emit MemberStatusChanged(account, previousStatus, STATUS_ACTIVE);
    }

    function suspend(address account) external onlyGovernor {
        _transition(account, STATUS_SUSPENDED);
    }

    function reinstate(address account) external onlyGovernor {
        Member storage member = _members[account];
        require(member.status == STATUS_SUSPENDED, "NOT_SUSPENDED");
        _transition(account, STATUS_ACTIVE);
    }

    /// @dev Off-boarding is terminal. Re-admission requires an explicit new enrolment,
    ///      so the event log always shows why an address regained the ability to attest.
    function offboard(address account) external onlyGovernor {
        _transition(account, STATUS_OFFBOARDED);
    }

    function _transition(address account, uint8 newStatus) private {
        Member storage member = _members[account];
        require(member.enrolledAt != 0, "NOT_ENROLLED");
        uint8 previousStatus = member.status;
        require(previousStatus != newStatus, "STATUS_UNCHANGED");
        require(previousStatus != STATUS_OFFBOARDED, "ALREADY_OFFBOARDED");
        member.status = newStatus;
        member.updatedAt = uint64(block.timestamp);
        if (previousStatus == STATUS_ACTIVE && activeMemberCount > 0) {
            activeMemberCount -= 1;
        }
        if (newStatus == STATUS_ACTIVE) {
            activeMemberCount += 1;
        }
        emit MemberStatusChanged(account, previousStatus, newStatus);
    }

    function isActiveMember(address account) external view returns (bool) {
        return _members[account].status == STATUS_ACTIVE;
    }

    function memberStatus(address account)
        external
        view
        returns (uint8 status, uint8 role, bytes32 orgId, uint64 enrolledAt, uint64 updatedAt)
    {
        Member memory member = _members[account];
        return (member.status, member.role, member.orgId, member.enrolledAt, member.updatedAt);
    }

    function memberCount() external view returns (uint256) {
        return _enrolled.length;
    }

    function memberAt(uint256 index) external view returns (address) {
        require(index < _enrolled.length, "INDEX_OUT_OF_RANGE");
        return _enrolled[index];
    }
}

/// @notice A non-transferable receipt that a pre-publication clearance check completed.
/// @dev Soulbound by construction: there is no transfer function to call. `locked` and the
///      `Locked` event follow ERC-5192 so wallets and indexers can see the intent. The token
///      is evidence of a completed check, not a property right.
contract CreatorProofClearanceReceipt {
    string public constant NAME = "CreatorProof Clearance Receipt";
    string public constant SYMBOL = "CPCR";
    string public constant MEANING =
        "This token records that a pre-publication clearance check completed for a specific evidence packet. It is not ownership of, a licence to, or a legal claim over the underlying work.";

    struct Receipt {
        address holder;
        bytes32 packetHash;
        bytes32 attestationUid;
        uint64 issuedAt;
        uint64 revokedAt;
    }

    CreatorProofMemberRegistry public immutable registry;
    address public issuer;
    uint256 public totalIssued;

    mapping(uint256 => Receipt) private _receipts;
    mapping(bytes32 => uint256) private _tokenByPacket;
    mapping(address => uint256) private _balances;

    event Issued(
        uint256 indexed tokenId,
        address indexed holder,
        bytes32 indexed packetHash,
        bytes32 attestationUid
    );
    event Revoked(uint256 indexed tokenId, address indexed revoker);
    event IssuerChanged(address indexed previous, address indexed current);
    /// @dev ERC-5192.
    event Locked(uint256 tokenId);

    modifier onlyIssuer() {
        require(msg.sender == issuer, "NOT_ISSUER");
        _;
    }

    constructor(address registryAddress, address initialIssuer) {
        require(registryAddress != address(0), "REGISTRY_REQUIRED");
        require(initialIssuer != address(0), "ISSUER_REQUIRED");
        registry = CreatorProofMemberRegistry(registryAddress);
        issuer = initialIssuer;
        emit IssuerChanged(address(0), initialIssuer);
    }

    function setIssuer(address newIssuer) external {
        require(msg.sender == registry.governor(), "NOT_GOVERNOR");
        require(newIssuer != address(0), "ISSUER_REQUIRED");
        address previous = issuer;
        issuer = newIssuer;
        emit IssuerChanged(previous, newIssuer);
    }

    function issue(address holder, bytes32 packetHash, bytes32 attestationUid)
        external
        onlyIssuer
        returns (uint256)
    {
        require(packetHash != bytes32(0), "PACKET_HASH_REQUIRED");
        require(attestationUid != bytes32(0), "ATTESTATION_UID_REQUIRED");
        require(_tokenByPacket[packetHash] == 0, "RECEIPT_EXISTS");
        // A receipt is only meaningful when its holder is currently accountable
        // to the network's governance.
        require(registry.isActiveMember(holder), "HOLDER_NOT_ACTIVE_MEMBER");

        totalIssued += 1;
        uint256 tokenId = totalIssued;
        _receipts[tokenId] = Receipt({
            holder: holder,
            packetHash: packetHash,
            attestationUid: attestationUid,
            issuedAt: uint64(block.timestamp),
            revokedAt: 0
        });
        _tokenByPacket[packetHash] = tokenId;
        _balances[holder] += 1;

        emit Issued(tokenId, holder, packetHash, attestationUid);
        emit Locked(tokenId);
        return tokenId;
    }

    function revoke(uint256 tokenId) external onlyIssuer {
        Receipt storage receipt = _receipts[tokenId];
        require(receipt.issuedAt != 0, "UNKNOWN_RECEIPT");
        require(receipt.revokedAt == 0, "ALREADY_REVOKED");
        receipt.revokedAt = uint64(block.timestamp);
        if (_balances[receipt.holder] > 0) {
            _balances[receipt.holder] -= 1;
        }
        emit Revoked(tokenId, msg.sender);
    }

    function locked(uint256 tokenId) external view returns (bool) {
        require(_receipts[tokenId].issuedAt != 0, "UNKNOWN_RECEIPT");
        return true;
    }

    function ownerOf(uint256 tokenId) external view returns (address) {
        Receipt memory receipt = _receipts[tokenId];
        require(receipt.issuedAt != 0, "UNKNOWN_RECEIPT");
        return receipt.holder;
    }

    function balanceOf(address holder) external view returns (uint256) {
        return _balances[holder];
    }

    function receiptOf(uint256 tokenId)
        external
        view
        returns (
            address holder,
            bytes32 packetHash,
            bytes32 attestationUid,
            uint64 issuedAt,
            uint64 revokedAt
        )
    {
        Receipt memory receipt = _receipts[tokenId];
        require(receipt.issuedAt != 0, "UNKNOWN_RECEIPT");
        return (
            receipt.holder,
            receipt.packetHash,
            receipt.attestationUid,
            receipt.issuedAt,
            receipt.revokedAt
        );
    }

    function receiptIdForPacket(bytes32 packetHash) external view returns (uint256) {
        return _tokenByPacket[packetHash];
    }

    /// @dev ERC-165 (0x01ffc9a7) and ERC-5192 (0xb45a3c0e). ERC-721 is intentionally absent:
    ///      claiming it while omitting transfer would be a false interface declaration.
    function supportsInterface(bytes4 interfaceId) external pure returns (bool) {
        return interfaceId == 0x01ffc9a7 || interfaceId == 0xb45a3c0e;
    }
}
