function greet(name: string): string {
  return `hello, ${name}`;
}

class Greeter {
  greet(name: string): string {
    return greet(name);
  }
}

function main() {
  const g = new Greeter();
  g.greet("world");
  greet("standalone");
}