// tailwind.config.js
/** @type {import('tailwindcss').Config} */
module.exports = {
    content: [
        "./*.html",
        "./*.js"
    ],
    darkMode: "class",
    theme: {
        extend: {
            colors: {
                primary: "#3b82f6",
                "background-light": "#f1f5f9",
                "background-dark": "#0f172a",
            },
            fontFamily: {
                sans: ["Inter", "Noto Sans JP", "Noto Sans KR", "sans-serif"],
            },
            borderRadius: {
                DEFAULT: "0.5rem",
            },
        },
    },
    plugins: [
        require('@tailwindcss/forms'),
        require('@tailwindcss/typography'),
        require('@tailwindcss/container-queries')
    ],
}
