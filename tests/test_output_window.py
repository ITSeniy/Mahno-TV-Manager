from director.output_window import PROGRAM_MIX_TYPE, open_program_projector


class FakeObsClient:
    def __init__(self):
        self.calls = []

    def open_video_mix_projector(self, video_mix_type, monitor_index=-1, projector_geometry=None):
        self.calls.append((video_mix_type, monitor_index, projector_geometry))


def test_open_program_projector_requests_the_program_mix():
    client = FakeObsClient()
    open_program_projector(client)

    assert client.calls == [(PROGRAM_MIX_TYPE, -1, None)]
