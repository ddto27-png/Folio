/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./app/**/*.{ts,tsx}', './components/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        serif: ['Georgia', 'Cambria', 'serif'],
      },
      colors: {
        cream: '#F8F5F0',
      },
    },
  },
  plugins: [],
}
