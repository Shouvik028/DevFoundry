def greet(name):
    return f"hello, {name}"


class Greeter:
    def greet(self, name):
        return greet(name)


def main():
    g = Greeter()
    g.greet("world")
    greet("standalone")