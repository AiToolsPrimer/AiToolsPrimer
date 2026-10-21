# Clients

One agency process per client. Create `config/clients/<name>.yaml` from `../agency.example.yaml`
(brand, handles, platforms, a different `panel_port`), then:

```bash
agency --client <name> doctor
agency --client <name> run      # its own dashboard on that client's panel_port
```

State lives in `state/<name>/` and assets in `assets/<name>/`; the knowledge base and the models are shared.
