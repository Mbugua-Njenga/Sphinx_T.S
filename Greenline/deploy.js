// This Deploys the smartcontract on the ethereum network
const hre = require("hardhat");
// Deploying with ether

async function main() {
  const [deployer] = await hre.ethers.getSigners();
  console.log("Deploying CarbonCredit with admin:", deployer.address);

  const CarbonCredit = await hre.ethers.getContractFactory("CarbonCredit");
  const contract = await CarbonCredit.deploy(deployer.address);
  await contract.waitForDeployment();

  console.log("CarbonCredit deployed to:", await contract.getAddress());
  console.log("Grant VERIFIER_ROLE to your backend's oracle address with:");
  console.log("  await contract.grantRole(await contract.VERIFIER_ROLE(), '<backend address>')");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
