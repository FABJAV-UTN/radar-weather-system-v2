/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        'nacion': '#003366',
        'nacion-light': '#004a99',
        'celeste': '#0099dd',
        'celeste-light': '#e8f4fd',
      },
      fontFamily: {
        display: ['"Barlow Condensed"', 'sans-serif'],
        body: ['Barlow', 'sans-serif'],
      }
    },
  },
  plugins: [],
}