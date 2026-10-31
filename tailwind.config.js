/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./templates/**/*.html",
    "./static/js/**/*.js",
    "./apps/**/*.py",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: [
          "Space Grotesk",
          "Arial",
          "sans-serif",
        ],
      },
    },
  },
  plugins: [],
};
