// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

/// @notice Minimal SchemaRegistry compatible with CreatorProof's EAS client ABI.
contract SchemaRegistry {
    struct SchemaRecord {
        bytes32 uid;
        address resolver;
        bool revocable;
        string schema;
    }

    mapping(bytes32 => SchemaRecord) private _schemas;
    event Registered(bytes32 indexed uid, address indexed registerer);

    function register(string calldata schema, address resolver, bool revocable) external returns (bytes32) {
        bytes32 uid = keccak256(abi.encodePacked(schema, resolver, revocable, msg.sender, block.timestamp, gasleft()));
        require(_schemas[uid].uid == bytes32(0), "SCHEMA_EXISTS");
        _schemas[uid] = SchemaRecord({uid: uid, resolver: resolver, revocable: revocable, schema: schema});
        emit Registered(uid, msg.sender);
        return uid;
    }

    function getSchema(bytes32 uid) external view returns (SchemaRecord memory) {
        return _schemas[uid];
    }
}

/// @notice Minimal EAS-compatible attester for CreatorProof local / olympiad demos.
contract EAS {
    struct AttestationRequestData {
        address recipient;
        uint64 expirationTime;
        bool revocable;
        bytes32 refUID;
        bytes data;
        uint256 value;
    }

    struct AttestationRequest {
        bytes32 schema;
        AttestationRequestData data;
    }

    struct Attestation {
        bytes32 uid;
        bytes32 schema;
        uint64 time;
        uint64 expirationTime;
        uint64 revocationTime;
        bytes32 refUID;
        address recipient;
        address attester;
        bool revocable;
        bytes data;
    }

    SchemaRegistry public immutable schemaRegistry;
    mapping(bytes32 => Attestation) private _attestations;

    event Attested(
        address indexed recipient,
        address indexed attester,
        bytes32 uid,
        bytes32 indexed schemaUID
    );

    event Revoked(bytes32 indexed uid, address indexed revoker);

    constructor(address registry) {
        schemaRegistry = SchemaRegistry(registry);
    }

    function getSchemaRegistry() external view returns (address) {
        return address(schemaRegistry);
    }

    function attest(AttestationRequest calldata request) external payable returns (bytes32) {
        SchemaRegistry.SchemaRecord memory record = schemaRegistry.getSchema(request.schema);
        require(record.uid != bytes32(0), "SCHEMA_UNKNOWN");
        if (!record.revocable) {
            require(!request.data.revocable, "SCHEMA_NOT_REVOCABLE");
        }

        bytes32 uid = keccak256(
            abi.encodePacked(
                request.schema,
                request.data.recipient,
                request.data.data,
                msg.sender,
                block.timestamp,
                gasleft()
            )
        );
        require(_attestations[uid].uid == bytes32(0), "UID_COLLISION");

        _attestations[uid] = Attestation({
            uid: uid,
            schema: request.schema,
            time: uint64(block.timestamp),
            expirationTime: request.data.expirationTime,
            revocationTime: 0,
            refUID: request.data.refUID,
            recipient: request.data.recipient,
            attester: msg.sender,
            revocable: request.data.revocable,
            data: request.data.data
        });

        emit Attested(request.data.recipient, msg.sender, uid, request.schema);
        return uid;
    }

    function isAttestationValid(bytes32 uid) external view returns (bool) {
        Attestation memory row = _attestations[uid];
        if (row.uid == bytes32(0)) return false;
        if (row.revocationTime != 0) return false;
        if (row.expirationTime != 0 && row.expirationTime <= block.timestamp) return false;
        return true;
    }

    function getAttestation(bytes32 uid) external view returns (Attestation memory) {
        return _attestations[uid];
    }

    function revoke(bytes32 uid) external {
        Attestation storage row = _attestations[uid];
        require(row.uid != bytes32(0), "NOT_FOUND");
        require(row.revocable, "NOT_REVOCABLE");
        require(row.attester == msg.sender, "NOT_ATTESTER");
        require(row.revocationTime == 0, "ALREADY_REVOKED");
        row.revocationTime = uint64(block.timestamp);
        emit Revoked(uid, msg.sender);
    }
}
