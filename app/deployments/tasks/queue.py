def task_queued(task_name: str, task_args: list, task_kwargs: dict) -> bool:  # noqa: PLR0912
    """Returns true if the task is already scheduled"""
    from buoy_barn.celery import app
    from celery.app.control import Control

    control = Control(app)
    inspect = control.inspect()

    try:
        for worker_tasks in inspect.active().values():
            for task in worker_tasks:
                if task["name"] == task_name and task["args"] == task_args:
                    return True
    except AttributeError:
        pass

    try:
        for worker_tasks in inspect.reserved().values():
            for task in worker_tasks:
                if task["name"] == task_name and task["args"] == task_args:
                    return True
    except AttributeError:
        pass

    try:
        for worker_tasks in inspect.scheduled().values():
            for task in worker_tasks:
                if task["name"] == task_name and task["args"] == task_args:
                    return True
    except AttributeError:
        pass

    return False
