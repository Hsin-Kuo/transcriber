<template>
  <div class="replace-toolbar">
    <input
      :value="findText"
      @input="$emit('update:findText', $event.target.value)"
      type="text"
      :placeholder="$t('replaceToolbar.find')"
      class="replace-input"
      @keydown.enter.prevent="$emit('replace-all')"
    />
    <input
      :value="replaceText"
      @input="$emit('update:replaceText', $event.target.value)"
      type="text"
      :placeholder="$t('replaceToolbar.replaceWith')"
      class="replace-input"
      @keydown.enter.prevent="$emit('replace-all')"
    />
    <button
      class="btn btn-primary"
      @click="$emit('replace-all')"
      :disabled="!findText"
    >
      {{ $t('replaceToolbar.replaceAll') }}
    </button>
  </div>
</template>

<script setup>
defineProps({
  findText: {
    type: String,
    default: ''
  },
  replaceText: {
    type: String,
    default: ''
  }
})

defineEmits(['update:findText', 'update:replaceText', 'replace-all'])
</script>

<style scoped>
/* Replace toolbar */
.replace-toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 20px;
  padding: 16px;
  background: rgba(163, 177, 198, 0.1);
  border-radius: 12px;
  align-items: stretch;
}

.replace-input {
  flex: 1;
  min-width: 150px;
  padding: 10px 14px;
  border: none;
  border-radius: 8px;
  background: var(--neu-bg);
  color: var(--neu-text);
  font-size: 0.95rem;
}

.replace-input:focus {
  outline: 2px solid var(--neu-primary);
}

@media (max-width: 768px) {
  .replace-toolbar {
    flex-direction: column;
  }
}
</style>
