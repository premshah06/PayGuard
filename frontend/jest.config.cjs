module.exports = {
  testEnvironment: 'jsdom',
  transform: {
    '^.+\\.(js|jsx)$': 'babel-jest',
  },
  moduleNameMapper: {
    '\\.(css|less|scss|sass)$': 'identity-obj-proxy',
    // Stub out canvas/GSAP/Lenis in tests
    '^gsap.*$': '<rootDir>/tests/__mocks__/gsap.js',
    '^@studio-freight/lenis$': '<rootDir>/tests/__mocks__/lenis.js',
  },
  setupFilesAfterFramework: ['./tests/setupTests.js'],
  testMatch: ['**/tests/**/*.test.{js,jsx}'],
  collectCoverageFrom: ['src/**/*.{js,jsx}'],
};
