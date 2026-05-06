// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Script, console} from "forge-std/Script.sol";
import {EnglishAuction} from "../src/EnglishAuction.sol";
import {MockNFT} from "../src/MockNFT.sol";

contract DeployScript is Script {
    function run() external {
        uint256 deployerKey = vm.envUint("PRIVATE_KEY");
        address deployer = vm.addr(deployerKey);

        // auction parameters
        uint256 baseDuration      = 1 hours;
        uint256 absoluteDuration  = 24 hours;
        uint256 extensionWindow   = 5 minutes;
        uint256 extensionDuration = 5 minutes;
        uint256 initialPrice      = 0.01 ether;   // 0.01 AVAX
        uint256 minBidIncrement   = 0.001 ether;  // 0.001 AVAX

        vm.startBroadcast(deployerKey);

        // Deploy mock NFT
        MockNFT nft = new MockNFT("https://x.com/Tim_Roughgarden/photo");
        uint256 tokenId = nft.mint(deployer);

        // Deploy the auction
        EnglishAuction auction = new EnglishAuction(
            address(nft),
            tokenId,
            baseDuration,
            absoluteDuration,
            extensionWindow,
            extensionDuration,
            initialPrice,
            minBidIncrement
        );

        vm.stopBroadcast();

        console.log("MockNFT deployed at:    ", address(nft));
        console.log("Token ID minted:        ", tokenId);
        console.log("EnglishAuction at:      ", address(auction));
        console.log("Deployer (seller):      ", deployer);
    }
}
