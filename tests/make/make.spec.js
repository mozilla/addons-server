const { spawnSync } = require('child_process');
const path = require('path');
const fs = require('fs');
const { globSync } = require('glob');
const { parse } = require('dotenv');

const rootPath = path.join(__dirname, '..', '..');
const envPath = path.join(rootPath, '.env');

function runSetup(env) {
  spawnSync('make', ['setup'], {
    env: { ...process.env, ...env },
    encoding: 'utf-8',
  });
}

function readEnvFile(name) {
  return parse(fs.readFileSync(envPath, { encoding: 'utf-8' }))[name];
}

test('map docker compose config', () => {
  const values = {
    DOCKER_VERSION: 'version',
    HOST_UID: 'uid',
  };

  fs.writeFileSync(envPath, '');
  runSetup(values);

  const { stdout: rawConfig } = spawnSync(
    'docker',
    ['compose', 'config', '--format', 'json'],
    { encoding: 'utf-8' },
  );

  const config = JSON.parse(rawConfig);
  const { web } = config.services;

  expect(web.image).toStrictEqual(
    `mozilla/addons-server:${values.DOCKER_VERSION}`,
  );
  expect(web.platform).toStrictEqual('linux/amd64');
  expect(web.environment.HOST_UID).toStrictEqual(values.HOST_UID);
  expect(config.volumes.data_mysqld.name).toStrictEqual(
    'addons-server_data_mysqld',
  );
});

describe('docker-bake.hcl', () => {
  function getBakeConfig(env = {}) {
    fs.writeFileSync(envPath, '');
    runSetup(env);
    const { stdout: output } = spawnSync(
      'make',
      ['docker_build_web', 'ARGS=--print'],
      {
        encoding: 'utf-8',
        env: { ...process.env, ...env },
      },
    );

    return output;
  }
  it('renders empty values for undefined variables', () => {
    const output = getBakeConfig();
    expect(output).toContain('"DOCKER_BUILD": ""');
    expect(output).toContain('"DOCKER_COMMIT": ""');
    expect(output).toContain('"DOCKER_VERSION": ""');
    expect(output).toContain('"target": "development"');
    expect(output).toContain('mozilla/addons-server:local');
  });

  it('renders custom DOCKER_BUILD', () => {
    const build = 'build';
    const output = getBakeConfig({ DOCKER_BUILD: build });
    expect(output).toContain(`"DOCKER_BUILD": "${build}"`);
  });

  it('renders custom DOCKER_COMMIT', () => {
    const commit = 'commit';
    const output = getBakeConfig({ DOCKER_COMMIT: commit });
    expect(output).toContain(`"DOCKER_COMMIT": "${commit}"`);
  });

  it('renders custom DOCKER_VERSION', () => {
    const version = 'version';
    const output = getBakeConfig({ DOCKER_VERSION: version });
    expect(output).toContain(`"DOCKER_VERSION": "${version}"`);
    expect(output).toContain(`mozilla/addons-server:${version}`);
  });

  it('renders custom DOCKER_DIGEST', () => {
    const digest = 'sha256:digest';
    const output = getBakeConfig({ DOCKER_DIGEST: digest });
    expect(output).toContain(`mozilla/addons-server@${digest}`);
  });

  it('renders custom target', () => {
    const target = 'target';
    const output = getBakeConfig({ DOCKER_TARGET: target });
    expect(output).toContain(`"target": "${target}"`);
  });
});

function standardPermutations(name, defaultValue) {
  return [
    {
      name,
      file: undefined,
      env: undefined,
      expected: defaultValue,
    },
    {
      name,
      file: 'file',
      env: undefined,
      expected: 'file',
    },
    {
      name,
      file: undefined,
      env: 'env',
      expected: 'env',
    },
    {
      name,
      file: 'file',
      env: 'env',
      expected: 'env',
    },
  ];
}

describe.each([
  {
    version: undefined,
    digest: undefined,
    tag: undefined,
    expected: 'mozilla/addons-server:local',
  },
  {
    version: 'version',
    digest: undefined,
    tag: undefined,
    expected: 'mozilla/addons-server:version',
  },
  {
    version: undefined,
    digest: 'sha256:digest',
    tag: undefined,
    expected: 'mozilla/addons-server@sha256:digest',
  },
  {
    version: 'version',
    digest: 'sha256:digest',
    tag: undefined,
    expected: 'mozilla/addons-server@sha256:digest',
  },
  {
    version: 'version',
    digest: 'sha256:digest',
    tag: 'previous',
    expected: 'mozilla/addons-server@sha256:digest',
  },
  {
    version: undefined,
    digest: undefined,
    tag: 'previous',
    expected: 'previous',
  },
])('DOCKER_TAG', ({ version, digest, tag, expected }) => {
  it(`version:${version}_digest:${digest}_tag:${tag}`, () => {
    fs.writeFileSync(envPath, '');
    runSetup({
      DOCKER_VERSION: version,
      DOCKER_DIGEST: digest,
      DOCKER_TAG: tag,
    });

    const actual = readEnvFile('DOCKER_TAG');
    expect(actual).toStrictEqual(expected);
  });
});

const testCases = [
  ...standardPermutations('DOCKER_TAG', 'mozilla/addons-server:local'),
  ...standardPermutations('DOCKER_TARGET', 'development'),
  ...standardPermutations('HOST_UID', process.getuid().toString()),
  ...standardPermutations(
    'COMPOSE_FILE',
    'docker-compose.yml:docker-compose.development.yml',
  ),
];

describe.each(testCases)('.env file', ({ name, file, env, expected }) => {
  it(`name:${name}_file:${file}_env:${env}`, () => {
    fs.writeFileSync(envPath, file ? `${name}=${file}` : '');

    runSetup({ [name]: env });

    const actual = readEnvFile(name);
    expect(actual).toStrictEqual(expected);
  });
});

const testedKeys = new Set(testCases.map(({ name }) => name));

// Keys testsed outside the scope of testCases
const skippedKeys = ['DOCKER_COMMIT', 'DOCKER_VERSION', 'DOCKER_BUILD', 'PWD'];

test('All dynamic properties in any docker compose file are referenced in the test', () => {
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
        if (!skippedKeys.includes(variable)) variableDefinitions.push(variable);
      }
    }
  }

  for (let variable of variableDefinitions) {
    expect(testedKeys).toContain(variable);
  }
});
