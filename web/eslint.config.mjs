import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";

const features = ["predictions", "match", "following", "review", "entry", "auth", "chat"];

export default defineConfig([
  ...nextVitals,
  ...nextTypescript,
  {
    files: ["src/**/*.{ts,tsx}"],
    rules: {
      "max-lines": [
        "error",
        { max: 400, skipBlankLines: false, skipComments: false },
      ],
    },
  },
  {
    files: ["src/components/**/*.{ts,tsx}", "src/lib/**/*.{ts,tsx}"],
    rules: {
      "no-restricted-imports": [
        "error",
        { patterns: ["@/features/*", "../features/*"] },
      ],
    },
  },
  ...features.map((feature) => ({
    files: [`src/features/${feature}/**/*.{ts,tsx}`],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: features
            .filter((other) => other !== feature)
            .flatMap((other) => [
              {
                group: [
                  `@/features/${other}/*`,
                  `../${other}/*`,
                  `../../${other}/*`,
                ],
                message: "跨功能只从 @/features/功能名 公开入口引用。",
              },
            ]).concat([
              {
                group: ["@/app/**", "../../app/**"],
                message: "功能模块不能反向引用应用路由。",
              },
            ]),
        },
      ],
    },
  })),
  ...features.map((feature) => ({
    files: [`src/features/${feature}/**/*.client.{ts,tsx}`],
    rules: {
      "no-restricted-imports": ["error", {
        patterns: [
          { group: ["**/*.server", "server-only", "**/demo-data*", "@/app/**"], message: "客户端不可导入服务端数据或应用路由。" },
          ...features.filter((other) => other !== feature).map((other) => ({
            group: [`@/features/${other}/*`, `../${other}/*`, `../../${other}/*`],
            message: "跨功能只从公开入口引用。",
          })),
        ],
      }],
    },
  })),
  globalIgnores([
    ".next/**",
    "next-env.d.ts",
    "coverage/**",
    "test-results/**",
    "playwright-report/**",
    "src/api/**",
  ]),
]);
