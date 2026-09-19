import { experimental_evaluate as evaluate } from 'ai';

async function readStdin() {
  let body = '';
  for await (const chunk of process.stdin) body += chunk;
  return body;
}

const getScore = (answer) => typeof answer?.score === 'number' ? answer.score : 0;

try {
  if (!process.env.AI_GATEWAY_API_KEY) throw new Error('AI_GATEWAY_API_KEY is not set');
  const input = JSON.parse((await readStdin()) || '{}');
  if (typeof input.prompt !== 'string' || !input.prompt.trim()) throw new Error('prompt is required');
  if (!input.targets || typeof input.targets !== 'object' || Array.isArray(input.targets)) throw new Error('targets are required');

  const result = await evaluate({
    model: 'typesafe-ai/jev',
    state: {
      task: input.prompt,
      routingPolicy: 'Prefer the least scarce capable coding agent. Devin SWE handles normal implementation. Astra is reserved for exceptional high-risk or highly ambiguous architecture work.',
    },
    questions: {
      route: {
        type: 'choice',
        instructions: 'Choose the best configured coding agent. Prefer Devin SWE for normal coding and avoid Astra unless the task clearly needs the strongest reasoning.',
        criteria: input.targets,
      },
      complexity: {
        type: 'score',
        instructions: 'How difficult is this software-engineering task overall?',
        criteria: ['trivial mechanical edit', 'routine implementation or bug fix', 'complex multi-component reasoning', 'exceptionally difficult end-to-end engineering'],
      },
      architectureImpact: {
        type: 'score',
        instructions: 'How much architecture or system design judgment is required?',
        criteria: ['none', 'localized design choice', 'cross-component architecture impact', 'major system architecture decision'],
      },
      blastRadius: {
        type: 'score',
        instructions: 'How large is the potential blast radius if the implementation is wrong?',
        criteria: ['very low', 'localized', 'multiple components or important data', 'production-wide, security-critical, or destructive'],
      },
      ambiguity: {
        type: 'score',
        instructions: 'How ambiguous are the requirements or likely root cause?',
        criteria: ['clear', 'minor unknowns', 'substantial investigation needed', 'highly ambiguous with many competing hypotheses'],
      },
    },
    maxRetries: 0,
    abortSignal: AbortSignal.timeout(8000),
    providerOptions: { gateway: { zeroDataRetention: true } },
  });

  const route = result.answers.route;
  const agent = route?.choice;
  if (typeof agent !== 'string' || !(agent in input.targets)) throw new Error('Jev returned an unknown route');
  const probability = route?.probabilities?.[agent];

  process.stdout.write(JSON.stringify({
    agent,
    confidence: typeof probability === 'number' ? probability : null,
    probabilities: route?.probabilities ?? {},
    scores: {
      complexity: getScore(result.answers.complexity),
      architecture_impact: getScore(result.answers.architectureImpact),
      blast_radius: getScore(result.answers.blastRadius),
      ambiguity: getScore(result.answers.ambiguity),
    },
  }) + '\n');
} catch (error) {
  process.stderr.write((error instanceof Error ? error.message : String(error)) + '\n');
  process.exitCode = 1;
}
