import { useState, useEffect } from 'react';
import { fetchStepModels } from '../lib/api';

export function useStepModels() {
  const [models, setModels] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        const data = await fetchStepModels();
        setModels(data);
      } catch (err) {
        setError('Failed to load models from environment.');
        console.error(err);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  return { models, loading, error };
}
