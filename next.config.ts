import type { NextConfig } from "next";

const repositoryName = process.env.GITHUB_REPOSITORY?.split("/")[1];
const githubPagesBasePath =
  process.env.GITHUB_ACTIONS === "true" && repositoryName
    ? `/${repositoryName}`
    : "";

const nextConfig: NextConfig = {
  output: "export",
  basePath: githubPagesBasePath,
  trailingSlash: true,
};

export default nextConfig;
