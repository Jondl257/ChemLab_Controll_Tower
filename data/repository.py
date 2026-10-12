from data.generator import generate_demo_data

class Repository:
    def __init__(self): self.data = generate_demo_data()
    def table(self, name): return self.data[name]
    def replace(self, name, value): self.data[name] = value
