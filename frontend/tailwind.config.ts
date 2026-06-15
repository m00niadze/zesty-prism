import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          DEFAULT: "#7c3aed",
          dark: "#5b21b6",
        },
      },
    },
  },
  plugins: [],
} satisfies Config;
