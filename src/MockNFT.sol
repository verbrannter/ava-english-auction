// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ERC721} from "@openzeppelin/contracts/token/ERC721/ERC721.sol";
import {Base64} from "@openzeppelin/contracts/utils/Base64.sol";

contract MockNFT is ERC721 {
    uint256 public nextTokenId;
    string private _imageURI;

    constructor(string memory imageURI_) ERC721("MockNFT", "MNFT") {
        _imageURI = imageURI_;
    }

    function tokenURI(uint256 tokenId) public view override returns (string memory) {
        _requireOwned(tokenId);
        string memory json = string.concat(
            '{"name":"MockNFT #', _toStr(tokenId),
            '","description":"Auction NFT","image":"', _imageURI, '"}'
        );
        return string.concat(
            "data:application/json;base64,",
            Base64.encode(bytes(json))
        );
    }

    function mint(address to) external returns (uint256 tokenId) {
        tokenId = nextTokenId++;
        _mint(to, tokenId);
    }

    function _toStr(uint256 v) private pure returns (string memory) {
        if (v == 0) return "0";
        uint256 j = v; uint256 len;
        while (j != 0) { len++; j /= 10; }
        bytes memory b = new bytes(len);
        while (v != 0) { len--; b[len] = bytes1(uint8(48 + v % 10)); v /= 10; }
        return string(b);
    }
}
