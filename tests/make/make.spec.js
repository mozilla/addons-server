const { spawnSync } = require('child_process');
const path = require('path');
const fs = require('fs');
const { globSync } = require('glob');

const rootPath = path.join(__dirname, '..', '..');
const envPath = path.join(rootPath, '.env');

const options = [false, true];
const frozenKeys = ['DOCKER_MYSQLD_VOLUME'];
const configurableKeys = [
  'DOCKER_VERSION',
  'HOST_UID',
  'SUPERUSER_EMAIL',
  'SUPERUSER_USERNAME',
];
const keys = [...frozenKeys, ...configurableKeys];

const product = (...arrays) =>
  arrays.reduce((a, b) => a.flatMap((d) => b.map((e) => [d, e].flat())));

const runCommand = (args, env = {}) => {
  const result = spawnSync('make', ['-f', 'Makefile-os', ...args], {
    env: {
      ...process.env,
      ...env,
    },
    encoding: 'utf-8',
  });
  if (result.status !== 0) throw new Error(result.stderr);
  return result;
};

const readEnv = () => {
  const exists = fs.existsSync(envPath);
  if (exists) {
    return require('dotenv').parse(
      fs.readFileSync(envPath, { encoding: 'utf-8' }),
    );
  }
  return require('dotenv').parse('');
};

const cleanEnv = () => {
  if (fs.existsSync(envPath)) fs.rmSync(envPath);
  const env = readEnv();

  for (const key of keys) {
    delete env[key];
  }

  return env;
};

const runMakeCreateEnvFile = (
  name,
  useFile = false,
  useEnv = false,
  useArgs = false,
) => {
  const env = cleanEnv();

  const args = ['create_env_file'];

  if (useFile) {
    fs.writeFileSync(envPath, `${name}=file`);
  }
  if (useEnv) {
    env[name] = 'env';
  }
  if (useArgs) {
    args.push(`${name}=args`);
  }

  runCommand(args, env);
  const result = readEnv()[name];

  console.debug(`
    name: ${name}
    args: ${JSON.stringify({ useFile, useEnv, useArgs }, null, 2)}
    command: make ${args.join(' ')}
    env: ${env[name] || 'undefined'}
    envFile: ${readEnv()[name] || 'undefined'}
    result: ${result}
  `);

  cleanEnv();
  return result;
};

const defaultValues = keys.reduce((acc, key) => {
  acc[key] = runMakeCreateEnvFile(key);
  return acc;
}, {});

describe('environment based configurations', () => {
  beforeEach(cleanEnv);

  describe.each(product(options, options, options, options, options))(
    'test_docker_compose_config',
    (useVersion, usePush, useUid, useEmail, useName) => {
      it(`
      test_version:${useVersion}_push:${usePush}_uid:${useUid}_email:${useEmail}_name:${useName}
    `, () => {
        const version = useVersion ? 'version' : defaultValues.DOCKER_VERSION;
        const uid = useUid ? '1000' : defaultValues.HOST_UID;
        const email = useEmail ? 'email' : defaultValues.SUPERUSER_EMAIL;
        const userName = useName ? 'name' : defaultValues.SUPERUSER_USERNAME;

        const env = {};

        const args = ['docker_compose_config'];

        if (useVersion) args.push(`DOCKER_VERSION=${version}`);
        if (useUid) args.push(`HOST_UID=${uid}`);
        if (useEmail) args.push(`SUPERUSER_EMAIL=${email}`);
        if (useName) args.push(`SUPERUSER_USERNAME=${userName}`);

        runCommand(['create_env_file'], env);

        const result = runCommand(args);

        const {
          services: { web },
        } = JSON.parse(result.stdout);

        expect(web.image).toStrictEqual(`mozilla/addons-server:${version}`);
        expect(web.platform).toStrictEqual('linux/amd64');

        expect(web.environment.HOST_UID).toStrictEqual(uid);
        expect(web.environment.SUPERUSER_EMAIL).toStrictEqual(email);
        expect(web.environment.SUPERUSER_USERNAME).toStrictEqual(userName);

        const builder = 'test_builder';
        const progress = 'test_progress';
        const push = usePush ? '--push' : '--load';
        const expectedBuildargs = `docker buildx bake web --progress=${progress} --builder=${builder} ${push}`;

        const { stdout: actualBuildArgs } = runCommand(['docker_build_args'], {
          DOCKER_PROGRESS: progress,
          DOCKER_BUILDER: builder,
          DOCKER_PUSH: usePush ? 'true' : 'false',
        });

        expect(actualBuildArgs.trim()).toStrictEqual(expectedBuildargs);

        const { stdout: bakeConfigOutput } = runCommand([
          'docker_build_config',
        ]);

        const bakeConfig = JSON.parse(bakeConfigOutput);

        expect(bakeConfig.target.web.platforms).toStrictEqual(['linux/amd64']);
      });
    },
  );

  test('docker compose substitution', () => {
    expect(new Set(Object.keys(defaultValues))).toStrictEqual(new Set(keys));

    const composeFiles = globSync('docker-compose*.yml', { cwd: rootPath });
    const variableDefinitions = [];

    for (let file of composeFiles) {
      const fileContent = fs.readFileSync(path.join(rootPath, file), {
        encoding: 'utf-8',
      });

      for (let line of fileContent.split('\n')) {
        const regex = /\${(.*?)(?::-.*)?}/g;
        let match;
        while ((match = regex.exec(line)) !== null) {
          const variable = match[1];
          variableDefinitions.push(variable);
        }
      }
    }

    for (let variable of variableDefinitions) {
      expect(keys).toContain(variable);
    }
  });

  describe.each(product(configurableKeys, options, options, options))(
    'test_configurable_keys',
    (name, useFile, useEnv, useArgs) => {
      it(`test_${name}_file:${useFile}_env:${useEnv}_args:${useArgs}`, () => {
        let expectedValue = defaultValues[name];

        if (!expectedValue) throw new Error(`expected value for ${name}.`);

        if (useFile) expectedValue = 'file';
        if (useEnv) expectedValue = 'env';
        if (useArgs) expectedValue = 'args';

        const actualValue = runMakeCreateEnvFile(
          name,
          useFile,
          useEnv,
          useArgs,
        );

        expect(actualValue).toStrictEqual(expectedValue);
      });
    },
  );

  describe.each(product(frozenKeys, options, options, options))(
    'test_frozen_keys',
    (name, useFile, useEnv, useArgs) => {
      it(`test_${name}_file:${useFile}_env:${useEnv}_args:${useArgs}`, () => {
        const expectedValue = defaultValues[name];
        const actualValue = runMakeCreateEnvFile(
          name,
          useFile,
          useEnv,
          useArgs,
        );
        expect(actualValue).toStrictEqual(expectedValue);
      });
    },
  );
});
