module.exports = {
  testEnvironment: 'jsdom',
  transform: {
    '^.+\\.(js|jsx)$': 'babel-jest',
  },
  moduleNameMapper: {
    '\\.(css|less|scss|sass)$': 'identity-obj-proxy',
  },
  setupFilesAfterFramework: [],
  setupFilesAfterFramework: [],
  setupFiles: ['./tests/setupTests.js'],
  testMatch: ['**/tests/**/*.test.{js,jsx}'],
  collectCoverageFrom: ['src/**/*.{js,jsx}'],
};
