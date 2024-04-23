#!/usr/bin/env node
import {spawnSync} from 'child_process';

const [,, name] = process.argv;
const url="http://nginx/__heartbeat__";
const time=60;
let wait_time=1;
let count=0;

const target = process.hrtime.bigint() + BigInt(time * 1e9);

async function ping() {
  const result = await spawnSync('curl', [url], {encoding: 'utf-8'});

  if (result.status === 0) {
    try {
      return JSON.parse(result.stdout);
    } catch (error) {
      console.error({error, result});
      return null;
    }
  }

  console.error(`Error: ${result.stderr}`);

  return null;
}

while (process.hrtime.bigint() < target) {
  count++;
  const timeLeft = Number(target - process.hrtime.bigint()) / 1e9;
  console.log(`Checking service: ${name} for ${count} time. (${timeLeft} seconds left)`);

  const data = await ping();

  if (data) {
    const service = data[name];

    if (!service) {
      console.error(`Service: ${name} not found`, {data});
      process.exit(1);
    }

    const state = service.state;

    if (state === true) {
      console.log(`Service: ${name} is healthy`);
      process.exit(0);
    } else {
      console.log(`Status: ${service.status}`);
    }
  }

  // Wait for the exponential backoff time
  await new Promise((resolve) => setTimeout(resolve, wait_time * 1000));

  // Double the wait time for the next iteration
  wait_time *= 2;
}

console.error(`Timeout reached for service: ${name}`);
process.exit(1);
