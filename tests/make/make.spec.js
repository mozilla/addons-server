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
    SUPERUSER_EMAIL: 'email',
    SUPERUSER_USERNAME: 'name',
  };

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
  expect(web.environment.SUPERUSER_EMAIL).toStrictEqual(values.SUPERUSER_EMAIL);
  expect(web.environment.SUPERUSER_USERNAME).toStrictEqual(
    values.SUPERUSER_USERNAME,
  );
  expect(config.volumes.data_mysqld.name).toStrictEqual(
    'addons-server_data_mysqld',
  );
});

function gitConfigUserEmail() {
  const { stdout: value } = spawnSync('git', ['config', 'user.email'], {
    encoding: 'utf-8',
  });

  return value.trim() || 'admin@mozilla.com';
}

function gitConfigUserName() {
  const { stdout: value } = spawnSync('git', ['config', 'user.name'], {
    encoding: 'utf-8',
  });
  return value.trim() || 'admin';
}

test('empty lines, comments, and numeric values are preserved', () => {
  const content = `
# DOCKER_VERSION=1
DOCKER_VERSION=:version

# Values with numeric name are preserved
1=2
# Empty values are preserved
2=
  `.trim();

  fs.writeFileSync(envPath, content);
  runSetup();

  const actual = fs.readFileSync(envPath, { encoding: 'utf-8' }).trim();
  expect(actual).toContain(content);
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

const testCases = [
  {
    name: 'DOCKER_VERSION',
    file: undefined,
    env: undefined,
    expected: ':local',
  },
  {
    name: 'DOCKER_VERSION',
    file: 'file',
    env: undefined,
    expected: ':file',
  },
  {
    name: 'DOCKER_VERSION',
    file: undefined,
    env: 'env',
    expected: ':env',
  },
  {
    name: 'DOCKER_VERSION',
    file: 'file',
    env: 'env',
    expected: ':env',
  },
  // Test that if the prefix already exists, it is not duplicated
  {
    name: 'DOCKER_VERSION',
    file: ':local',
    env: undefined,
    expected: ':local',
  },
  // Test that if the prefix already exists, it is not duplicated
  {
    name: 'DOCKER_VERSION',
    file: '@sha256:local',
    env: undefined,
    expected: '@sha256:local',
  },
  {
    name: 'DOCKER_VERSION',
    file: 'sha256:local',
    env: undefined,
    expected: '@sha256:local',
  },
  {
    name: 'DOCKER_VERSION',
    file: undefined,
    env: '@sha256:local',
    expected: '@sha256:local',
  },
  ...standardPermutations('HOST_UID', process.getuid().toString()),
  ...standardPermutations('SUPERUSER_EMAIL', gitConfigUserEmail()),
  ...standardPermutations('SUPERUSER_USERNAME', gitConfigUserName()),
  {
    name: 'FOO',
    file: 'Bar',
    env: undefined,
    expected: 'Bar',
  },
  ...standardPermutations('COMPOSE_FILE', 'docker-compose.yml:docker-compose.build.yml'),
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
