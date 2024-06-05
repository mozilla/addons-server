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

test('version.json', () => {
  runSetup({
    DOCKER_VERSION: 'version',
    DOCKER_COMMIT: '123',
    VERSION_BUILD_URL: 'https://',
  });

  const version = require(path.join(rootPath, 'version.json'));

  expect(version.version).toStrictEqual('version');
  expect(version.commit).toStrictEqual('123');
  expect(version.build).toStrictEqual('https://');
  expect(version.source).toStrictEqual(
    'https://github.com/mozilla/addons-server',
  );
});

test('map docker compose config', () => {
  const values = {
    DOCKER_VERSION: 'version',
    HOST_UID: 'uid',
  };

  fs.writeFileSync(envPath, '');
  runSetup(values);

  const { stdout: rawConfig } = spawnSync(
    'docker',
    ['compose', 'config', 'web', '--format', 'json'],
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
  ...standardPermutations('COMPOSE_FILE', 'docker-compose.yml'),
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
        variableDefinitions.push(variable);
      }
    }
  }

  for (let variable of variableDefinitions) {
    expect(testedKeys).toContain(variable);
  }
});
