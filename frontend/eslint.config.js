// ESLint 9 flat config — Vue 3 strongly-recommended + 寬鬆漸進策略
import js from '@eslint/js'
import pluginVue from 'eslint-plugin-vue'
import globals from 'globals'

export default [
  // 全域 ignores
  {
    ignores: [
      'dist/**',
      'node_modules/**',
      '.vite/**',
      '.vite-cache/**',
      'eslint.config.js',
    ],
  },

  // Vite 設定檔走 Node 環境（用 process / __dirname 等）
  {
    files: ['vite.config.*.js', 'vite.config.js'],
    languageOptions: {
      globals: {
        ...globals.node,
      },
    },
  },

  // JS 基本規則
  js.configs.recommended,

  // Vue SFC 規則
  ...pluginVue.configs['flat/strongly-recommended'],

  // 全域語言環境
  {
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      globals: {
        ...globals.browser,
        ...globals.es2024,
      },
    },
    rules: {
      // 既有 codebase 不強制這些 style preference（避免大量 warning）
      'vue/multi-word-component-names': 'off',
      'vue/attribute-hyphenation': 'off',
      'vue/v-on-event-hyphenation': 'off',
      'vue/no-v-html': 'off',
      'vue/html-self-closing': 'off',
      'vue/max-attributes-per-line': 'off',
      'vue/html-indent': 'off',
      'vue/html-closing-bracket-newline': 'off',
      'vue/singleline-html-element-content-newline': 'off',
      'vue/multiline-html-element-content-newline': 'off',
      // 既有 JS 大量 catch (e) 未使用——容忍
      'no-unused-vars': ['warn', {
        argsIgnorePattern: '^_',
        varsIgnorePattern: '^_',
        caughtErrors: 'none',
      }],
      // console 是日常 debug 工具
      'no-console': 'off',
      // CJK regex 內含 U+3000 / 全形標點是合法的（match 中文文字輸入）
      'no-irregular-whitespace': ['error', { skipRegExps: true, skipStrings: true }],
    },
  },
]
