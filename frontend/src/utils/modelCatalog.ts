import type { ModelCatalog } from '../types'

export function validModelSelection(
  catalog: ModelCatalog | null, model: string, dimension: number | undefined, tag: string,
): boolean {
  return !!catalog && !!catalog.embedding_models[model] && !!catalog.tag_models[tag]
    && catalog.embedding_models[model].dimensions.includes(dimension as number)
    && catalog.vector_space.model === model && catalog.vector_space.dimension === dimension
}

export function validateCatalog(value: unknown): value is ModelCatalog {
  if (!value || typeof value !== 'object') return false
  const catalog = value as ModelCatalog
  try {
    const { defaults, vector_space, embedding_models, tag_models } = catalog
    return Object.keys(embedding_models).length > 0 && Object.keys(tag_models).length > 0
      && Object.values(embedding_models).every(model => typeof model.name === 'string'
        && model.name.length > 0 && Array.isArray(model.dimensions) && model.dimensions.length > 0
        && model.dimensions.every(d => Number.isInteger(d) && d > 0)
        && model.dimensions.includes(model.default_dimension))
      && Object.values(tag_models).every(model => typeof model.name === 'string' && model.name.length > 0)
      && validModelSelection(catalog, defaults.embedding_model, defaults.embedding_dimension, defaults.tag_model)
      && Number.isFinite(defaults.text_search_min_score)
      && defaults.text_search_min_score >= 0 && defaults.text_search_min_score <= 1
      && [vector_space.collection, vector_space.corpus_instruction_version, vector_space.query_instruction_version]
        .every(v => typeof v === 'string' && v.length > 0)
  } catch {
    return false
  }
}

export function validTosDirectory(value: string): boolean {
  return /^tos:\/\/[^/?#@: \t\r\n]+\/[^\r\n]*$/.test(value)
}
