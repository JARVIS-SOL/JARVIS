# — coding: utf-8 –
import openai
import json
import logging
import sys
import argparse
from langchain.chat_models import ChatOpenAI
from langchain.prompts import (
    ChatPromptTemplate,
    MessagesPlaceholder,
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate
)
from langchain import LLMChain
import numpy as np
import requests
import os
import subprocess
import re
import importlib.util
from sklearn.metrics.pairwise import cosine_similarity
import pickle
from util import *
from tqdm import tqdm

openai.api_key = os.environ["OPENAI_API_KEY"]


def get_last_processed_index(progress_file):
    """Retrieve the last processed index from the progress file."""
    if os.path.exists(progress_file):
        with open(progress_file, 'r', encoding='utf-8') as f:
            last_index = f.read().strip()
            return int(last_index) if last_index else 0
    else:
        return 0


def update_progress(progress_file, index):
    """Update the last processed index in the progress file."""
    with open(progress_file, 'w', encoding='utf-8') as f:
        f.write(str(index))


def choose_tool(question, Tool_dic, tool_used, model_name):
    chat = ChatOpenAI(model_name=model_name)
    template = "You are a helpful assistant."
    system_message_prompt = SystemMessagePromptTemplate.from_template(template)
    human_message_prompt = HumanMessagePromptTemplate.from_template(
        "This is the user's question: {question}\n"
        "These are the tools you can select to solve the question:\n"
        "Tool List:\n"
        "{Too_list}\n\n"
        "Please note that: \n"
        "1. You should only chooce one tool the Tool List to solve this question.\n"
        "2. You must ONLY output the ID of the tool you chose in a parsible JSON format. Two example outputs look like:\n"
        "'''\n"
        "Example 1: {{\"ID\": 1}}\n"
        "Example 2: {{\"ID\": 2}}\n"
        "'''\n"
        "Output:"
    )
    chat_prompt = ChatPromptTemplate.from_messages([system_message_prompt, human_message_prompt])
    chain = LLMChain(llm=chat, prompt=chat_prompt)
    ind = 0
    Tool_list = []
    for ele in Tool_dic:
        for key in ele.keys():
            if str(key) not in tool_used:
                Tool_list.append(f'''ID: {key}\n{ele[key]}''')
    while True:
        try:
            result = chain.run(question=question,
                               Too_list=Tool_dic)
            clean_answer = eval(result.split("(")[0].strip())
            # clean_answer = lowercase_parameter_keys(clean_answer)
            # print(clean_answer)
            break
        except Exception as e:
            print(f"choose tool fails: {e}")
            print(result)
            if ind > 10:
                return -1
            ind += 1
            continue
    return clean_answer


def task_decompose(question, Tool_dic, model_name):
    chat = ChatOpenAI(model_name=model_name)
    template = "You are a helpful assistant."
    system_message_prompt = SystemMessagePromptTemplate.from_template(template)
    human_message_prompt = HumanMessagePromptTemplate.from_template(
        "You need to decompose a complex user's question into some simple subtasks and let the model execute it step by step.\n"
        "This is the user's question: {question}\n"
        "This is tool list:\n"
        "{Tool_list}\n"
        "Please note that: \n"
        "1. You should only decompose this complex user's question into some simple subtasks which can be executed easily by using one single tool in the tool list.\n"
        "2. If one subtask need the results from other subtask, you can should write clearly. For example:"
        "{{\"Tasks\": [\"Convert 23 km/h to X km/min by 'divide_'\", \"Multiply X km/min by 45 min to get Y by 'multiply_'\"]}}\n"
        "3. You must ONLY output in a parsible JSON format. An example output looks like:\n"
        "'''\n"
        "{{\"Tasks\": [\"Task 1\", \"Task 2\", ...]}}\n"
        "'''\n"
        "Output:"
    )
    chat_prompt = ChatPromptTemplate.from_messages([system_message_prompt, human_message_prompt])
    chain = LLMChain(llm=chat, prompt=chat_prompt)
    Tool_list = []
    for ele in Tool_dic:
        Tool_list.append(str(ele))
    ind = 0
    while True:
        try:
            result = chain.run(question=question, Tool_list=Tool_list)
            result = eval(result.split('\n\n')[0])
            a = result["Tasks"]
            break
        except Exception as e:
            print(f"task decompose fails: {e}")
            if ind > 10:
                return -1
            ind += 1
            continue
    return result


def task_topology(question, task_ls, model_name):
    chat = ChatOpenAI(model_name=model_name)
    template = "You are a helpful assistant."
    system_message_prompt = SystemMessagePromptTemplate.from_template(template)
    human_message_prompt = HumanMessagePromptTemplate.from_template(
        "Given a complex user's question, I have decompose this question into some simple subtasks"
        "I think there exists a logical connections and order amontg the tasks. "
        "Thus you need to help me output this logical connections and order.\n"
        "You must ONLY output in a parsible JSON format with the following format:\n"
        "'''\n"
        "[{{\"task\": task, \"id\", task_id, \"dep\": [dependency_task_id1, dependency_task_id2, ...]}}]\n"
        "'''\n"
        "The \"dep\" field denotes the id of the previous task which generates a new resource upon which the current task depends. If there are no dependencies, set \"dep\" to -1.\n\n"
        "This is user's question: {question}\n"
        "These are subtasks of this question:\n"
        "{task_ls}\n"
        "Output: "
    )
    chat_prompt = ChatPromptTemplate.from_messages([system_message_prompt, human_message_prompt])
    chain = LLMChain(llm=chat, prompt=chat_prompt)
    ind = 0
    while True:
        try:
            result = chain.run(question=question, task_ls=task_ls)
            result = eval(result)
            for i in range(len(result)):
                if isinstance(result[i]['dep'], str):
                    temp = []
                    for ele in result[i]['dep'].split(','):
                        temp.append(int(ele))
                    result[i]['dep'] = temp
                elif isinstance(result[i]['dep'], int):
                    result[i]['dep'] = [result[i]['dep']]
                elif isinstance(result[i]['dep'], list):
                    temp = []
                    for ele in result[i]['dep']:
                        temp.append(int(ele))
                    result[i]['dep'] = temp
                elif result[i]['dep'] == -1:
                    result[i]['dep'] = [-1]
            a = result[i]['dep'][0]
            return result
        except Exception as e:
            print(f"task topology fails: {e}")
            if ind > 10:
                return -1
            ind += 1
            continue
    return result


def answer_generation_direct(task, model_name):
    chat = ChatOpenAI(model_name=model_name)
    template = "You are a helpful assistant."
    system_message_prompt = SystemMessagePromptTemplate.from_template(template)
    human_message_prompt = HumanMessagePromptTemplate.from_template(
        "You need to answer the user's question.\n"
        "This is the user's question: {task}\n"
        "Output:"
    )
    chat_prompt = ChatPromptTemplate.from_messages([system_message_prompt, human_message_prompt])
    chain = LLMChain(llm=chat, prompt=chat_prompt)
    result = chain.run(task=task)
    return result


def choose_parameter(API_instruction, api, api_dic, question, model_name):
    chat = ChatOpenAI(model_name=model_name)
    template = "You are a helpful assistant."
    system_message_prompt = SystemMessagePromptTemplate.from_template(template)
    human_message_prompt = HumanMessagePromptTemplate.from_template(
        "This is an API tool documentation. Given a user's question, you need to output parameters according to the API tool documentation to successfully call the API to solve the user's question.\n"
        "This is API tool documentation: {api_dic}\n"
        "Please note that: \n"
        "1. The Example in the API tool documentation can help you better understand the use of the API.\n"
        "2. Ensure the parameters you output are correct. The output must contain the required parameters, and can contain the optional parameters based on the question. If no paremters in the required parameters and optional parameters, just leave it as {{\"Parameters\":{{}}}}\n"
        "3. If the user's question mentions other APIs, you should ONLY consider the API tool documentation I give and do not consider other APIs.\n"
        "4. If you need to use this API multiple times, please set \"Parameters\" to a list.\n"
        "5. You must ONLY output in a parsible JSON format. Two examples output looks like:\n"
        "'''\n"
        "Example 1: {{\"Parameters\":{{\"input\": [1,2,3]}}}}\n"
        "Example 2: {{\"Parameters\":[{{\"input\": [1,2,3]}}, {{\"input\": [2,3,4]}}]}}\n"
        "'''\n"
        "This is user's question: {question}\n"
        "Output:\n"
    )
    chat_prompt = ChatPromptTemplate.from_messages([system_message_prompt, human_message_prompt])
    chain = LLMChain(llm=chat, prompt=chat_prompt)
    ind = 0
    while True:
        try:
            result = chain.run(api_dic=api_dic,
                               question=question, )
            clean_answer = eval(
                result.replace(": true", ": True").replace(":true", ": True").replace(":false", ": False").replace(
                    ": false", ": False").replace("```", "").strip())
            a = clean_answer["Parameters"]

            return a
        except Exception as e:
            print(f"Choose Parameter fails: {e}")
            if ind > 10:
                return -1
            ind += 1
            continue
    return a


def choose_parameter_depend(API_instruction, api, api_dic, question, model_name, previous_log):
    chat = ChatOpenAI(model_name=model_name)
    template = "You are a helpful assistant."
    system_message_prompt = SystemMessagePromptTemplate.from_template(template)
    human_message_prompt = HumanMessagePromptTemplate.from_template(
        "Given a user's question and a API tool documentation, you need to output parameters according to the API tool documentation to successfully call the API to solve the user's question.\n"
        "Please note that: \n"
        "1. The Example in the API tool documentation can help you better understand the use of the API.\n"
        "2. Ensure the parameters you output are correct. The output must contain the required parameters, and can contain the optional parameters based on the question. If no paremters in the required parameters and optional parameters, just leave it as {{\"Parameters\":{{}}}}\n"
        "3. If the user's question mentions other APIs, you should ONLY consider the API tool documentation I give and do not consider other APIs.\n"
        "4. The question may have dependencies on answers of other questions, so we will provide logs of previous questions and answers for your reference.\n"
        "5. If you need to use this API multiple times,, please set \"Parameters\" to a list.\n"
        "6. You must ONLY output in a parsible JSON format. Two examples output looks like:\n"
        "'''\n"
        "Example 1: {{\"Parameters\":{{\"input\": [1,2,3]}}}}\n"
        "Example 2: {{\"Parameters\":[{{\"input\": [1,2,3]}}, {{\"input\": [2,3,4]}}]}}\n"
        "'''\n"
        "There are logs of previous questions and answers: \n {previous_log}\n"
        "This is the current user's question: {question}\n"
        "This is API tool documentation: {api_dic}\n"
        "Output:\n"
    )
    chat_prompt = ChatPromptTemplate.from_messages([system_message_prompt, human_message_prompt])
    chain = LLMChain(llm=chat, prompt=chat_prompt)
    ind = 0
    while True:
        try:
            result = chain.run(api_dic=api_dic,
                               question=question,
                               previous_log=previous_log)
            clean_answer = eval(
                result.replace(": true", ": True").replace(": false", ": False").replace("```", "").strip())
            a = clean_answer["Parameters"]

            return a
        except Exception as e:
            print(f"choose parameter depend fails: {e}")
            if ind > 10:
                return -1
            ind += 1
            continue
    return a


def Call_function(B, arg, id):
    app_path = 'data_funcqa/funchub/math.py'
    spec = importlib.util.spec_from_file_location('math', app_path)
    app_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(app_module)
    if hasattr(app_module, B):
        function_B = getattr(app_module, B)
        try:
            call_result = function_B(arg['input'])
            return call_result
        except Exception as e:
            try:
                arg = {change_name(k.lower()): v for k, v in arg.items()}
                call_result = function_B(arg['input'])
                return call_result
            except Exception as e:
                try:
                    arg = {change_name(k.lower()): v for k, v in arg.items()}
                    arg = {change_name(k.replace("-", "_")): v for k, v in arg.items()}
                    call_result = function_B(arg['input'])
                    return call_result
                except Exception as e:
                    print(f"fails: {e}")
                    with open('wrong_log.json', 'a+', encoding='utf-8') as f:
                        line = json.dumps({
                            "id": id,
                            "parameters": arg,
                            "wrong": str(e)
                        }, ensure_ascii=False)
                        f.write(line + '\n')
                    return -1
    else:
        with open('wrong_log.json', 'a+', encoding='utf-8') as f:
            line = json.dumps({
                "id": id,
                "parameters": arg,
                "wrong": f"No function named {B} in {app_path}"
            }, ensure_ascii=False)
            f.write(line + '\n')
        return (f"No function named {B} in {app_path}")


def retrieval(question, Tool_dic, dataset, tool_used, ind, model_name, previous_log=None):
    tool_id = choose_tool(question, Tool_dic, tool_used, model_name)
    if tool_id == -1:
        return tool_id, "", "", "", ""
    tool_instruction = dataset[str(tool_id["ID"])]
    API_instruction = tool_instruction["API_description"]
    API_tool = tool_instruction["standardized_name"]

    api_selection = [API_tool]
    api_result = []
    for api in api_selection:
        if previous_log is None:
            parameter = choose_parameter(API_instruction, api,
                                         tool_instruction["Usage"], question, model_name)
        else:
            parameter = choose_parameter_depend(API_instruction, api,
                                                tool_instruction["Usage"],
                                                question, model_name, previous_log)
        if parameter == -1:
            continue
        api_result.append({"api_name": api, "parameters": parameter})
    if len(api_result) == 0:
        call_result = ""
        return tool_id, api_result, call_result, tool_instruction, API_instruction
    if isinstance(api_result, set) or isinstance(api_result, list):
        call_results = []
        for api in api_result:
            if isinstance(api["parameters"], dict):
                parameters = {}
                for key in api["parameters"]:
                    value = api["parameters"][key]
                    key = change_name(key)
                    parameters[key] = value
                call_result = Call_function(API_tool, parameters, ind)
                if call_result == -1:
                    continue
                call_results.append(str(call_result))
            elif isinstance(api["parameters"], list):
                for para_ls in api["parameters"]:
                    parameters = {}
                    for key in para_ls:
                        value = para_ls[key]
                        key = change_name(key)
                        parameters[key] = value
                    call_result = Call_function(API_tool, parameters, ind)
                    if call_result == -1:
                        continue
                    call_results.append(str(call_result))
        call_result = '\n\n'.join(call_results)
    elif isinstance(api_result, dict):
        api = api_result
        if isinstance(api["parameters"], dict):
            parameters = {}
            for key in api["parameters"]:
                value = api["parameters"][key]
                key = change_name(key)
                parameters[key] = value
            call_result = Call_function(API_tool, parameters, ind)
        elif isinstance(api["parameters"], list):
            call_results = []
            for para_ls in api["parameters"]:
                parameters = {}
                for key in para_ls:
                    value = para_ls[key]
                    key = change_name(key)
                    parameters[key] = value
                call_result = Call_function(API_tool, parameters, ind)
                if call_result == -1:
                    continue
                call_results.append(str(call_result))
            call_result = '\n\n'.join(call_results)

    return tool_id, api_result, call_result, tool_instruction, API_instruction


def answer_generation(question, API_instruction, call_result, model_name):
    chat = ChatOpenAI(model_name=model_name)
    template = "You are a helpful assistant."
    system_message_prompt = SystemMessagePromptTemplate.from_template(template)
    human_message_prompt = HumanMessagePromptTemplate.from_template(
        "You should answer the question based on the response output by the API tool."
        "Please note that:\n"
        "1. Answer the question in natural language based on the API response reasonably and effectively.\n"
        "2. The user cannot directly get API response, "
        "so you need to make full use of the response and give the information "
        "in the response that can satisfy the user's question in as much detail as possible.\n"
        "3. If the API tool does not provide useful information in the response, "
        "please answer with your knowledge.\n"
        "This is the user's question:\n {question}\n"
        "This is the API response:\n {call_result}\n"
        "Output:"
    )
    chat_prompt = ChatPromptTemplate.from_messages([system_message_prompt, human_message_prompt])
    chain = LLMChain(llm=chat, prompt=chat_prompt)
    ind = 0
    while True:
        try:
            result = chain.run(question=question,
                               API_instruction=API_instruction,
                               call_result=call_result, )
            break
        except Exception as e:
            print(f"answer generation fails: {e}")
            if ind > 2:
                return -1
            ind += 1
            continue
    return result


def answer_generation_depend(question, API_instruction, call_result, previous_log, model_name):
    chat = ChatOpenAI(model_name=model_name)
    template = "You are a helpful assistant."
    system_message_prompt = SystemMessagePromptTemplate.from_template(template)
    human_message_prompt = HumanMessagePromptTemplate.from_template(
        "You should answer the question based on the response output by the API tool."
        "Please note that:\n"
        "1. Try to organize the response into a natural language answer.\n"
        "2. We will not show the API response to the user, "
        "thus you need to make full use of the response and give the information "
        "in the response that can satisfy the user's question in as much detail as possible.\n"
        "3. If the API tool does not provide useful information in the response, "
        "please answer with your knowledge.\n"
        "4. The question may have dependencies on answers of other questions, so we will provide logs of previous questions and answers.\n"
        "There are logs of previous questions and answers: \n {previous_log}\n"
        "This is the user's question: {question}\n"
        "This is the response output by the API tool: \n{call_result}\n"
        "We will not show the API response to the user, "
        "thus you need to make full use of the response and give the information "
        "in the response that can satisfy the user's question in as much detail as possible.\n"
        "Output:"
    )
    chat_prompt = ChatPromptTemplate.from_messages([system_message_prompt, human_message_prompt])
    chain = LLMChain(llm=chat, prompt=chat_prompt)
    ind = 0
    while True:
        try:
            result = chain.run(question=question,
                               API_instruction=API_instruction,
                               call_result=call_result,
                               previous_log=previous_log)
            break
        except Exception as e:
            print(f"answer generation depend fails: {e}")
            if ind > 2:
                return -1
            ind += 1
            continue
    return result


def answer_summarize(question, answer_task, model_name):
    chat = ChatOpenAI(model_name=model_name)
    template = "You are a helpful assistant."
    system_message_prompt = SystemMessagePromptTemplate.from_template(template)
    human_message_prompt = HumanMessagePromptTemplate.from_template(
        "We break down a complex user's problems into simple subtasks and provide answers to each simple subtask. "
        "You need to organize these answers to each subtask and form a self-consistent final answer to the user's question\n"
        "This is the user's question: {question}\n"
        "These are subtasks and their answers: {answer_task}\n"
        "Final answer:"
    )
    chat_prompt = ChatPromptTemplate.from_messages([system_message_prompt, human_message_prompt])
    chain = LLMChain(llm=chat, prompt=chat_prompt)
    result = chain.run(question=question, answer_task=answer_task)
    return result


def answer_check(question, answer, model_name):
    chat = ChatOpenAI(model_name=model_name)
    template = "You are a helpful assistant."
    system_message_prompt = SystemMessagePromptTemplate.from_template(template)
    human_message_prompt = HumanMessagePromptTemplate.from_template(
        "Please check whether the response can reasonably and accurately answer the question."
        "If can, please output 'YES'; If not, please output 'NO'\n"
        "You need to give reasons first and then decide whether the response can reasonably and accurately answer the question. You must only output in a parsible JSON format. Two example outputs look like:\n"
        "Example 1: {{\"Reason\": \"The reason why you think the response can reasonably and accurately answer the question\", \"Choice\": \"Yes\"}}\n"
        "Example 2: {{\"Reason\": \"The reason why you think the response cannot reasonably and accurately answer the question\", \"Choice\": \"No\"}}\n"
        "This is the user's question: {question}\n"
        "This is the response: {answer}\n"
        "Output: "
    )
    chat_prompt = ChatPromptTemplate.from_messages([system_message_prompt, human_message_prompt])
    chain = LLMChain(llm=chat, prompt=chat_prompt)
    result = chain.run(question=question, answer=answer)
    if 'yes'.lower() in eval(result)["Choice"].lower():
        return 1
    else:
        return -1


def task_execution_mh(data_type, start_index, total_files,
                      retrieval_num, ind, model_name, dataset,
                      Tool_dic, test_data, progress_file):
    with tqdm(total=total_files, desc="Processing files", initial=start_index) as pbar:
        for i, data in enumerate(test_data[start_index:], start=start_index):
            answer_ls = []
            question = data["question"]
            print(question)
            temp = task_decompose(question, Tool_dic, model_name)['Tasks']
            task_ls = []
            for t in range(len(temp)):
                task_ls.append({"task": temp[t], "id": t + 1})
            task_ls = task_topology(question, task_ls, model_name)
            task_depend = {'Original Question': question}
            for task_dic in task_ls:
                task_depend[task_dic['id']] = {'task': task_dic['task'], 'answer': ''}
            answer_task = []
            tool_instruction_ls = []
            api_result_ls = []
            call_result_ls = []
            tool_check_reason_ls = []
            for task_dic in task_ls:
                task = task_dic['task']
                print("Do need tool.")
                tool_used = []
                depend_id = [1]
                for r in range(retrieval_num):
                    if depend_id[0] == -1:
                        tool_id, api_result, call_result, tool_instruction, API_instruction = retrieval(task, Tool_dic,
                                                                                                        dataset,
                                                                                                        tool_used, ind,
                                                                                                        model_name)
                        if len(str(call_result)) > 5000:
                            call_result = str(call_result)[:5000]
                        answer = answer_generation(task, API_instruction, call_result, model_name)
                    else:
                        previous_log = task_depend
                        tool_id, api_result, call_result, tool_instruction, API_instruction = retrieval(task, Tool_dic,
                                                                                                        dataset,
                                                                                                        tool_used, ind,
                                                                                                        model_name,
                                                                                                        previous_log=previous_log)
                        if len(str(call_result)) > 5000:
                            call_result = str(call_result)[:5000]
                        answer = answer_generation_depend(task, API_instruction, call_result, previous_log, model_name)

                    check_index = 1
                    if str(call_result).strip() == '-1' or str(call_result).strip() == '':
                        check_index = -1
                    if check_index == 1:
                        answer_task.append({'task': task, 'answer': answer})
                        tool_instruction_ls.append(tool_instruction)
                        api_result_ls.append(api_result)
                        call_result_ls.append(call_result)
                        break
                    else:
                        answer_ls.append({'task': task, 'answer': answer})
                        try:
                            tool_used.append(str(tool_id["ID"]))
                        except:
                            continue
                        print('****Try Again****')

                task_depend[task_dic['id']]['answer'] = answer
            final_answer = answer_summarize(question, answer_task, model_name)
            check_index = answer_check(question, final_answer, model_name)
            ind = ind + 1
            with open(f"FuncQA_{data_type}_{model_name}_easytool.jsonl", 'a+', encoding='utf-8') as f:
                line = json.dumps({
                    "ID": ind,
                    "question": question,
                    "final_answer": final_answer,
                    "subtask": task_ls,
                    "answer_subtask": answer_task,
                    "answer_wrong": answer_ls,
                    "check_index": check_index,
                    "execute_log": {
                        "api_result_ls": api_result_ls,
                        "call_result_ls": call_result_ls,
                        "tool_check_reason_ls": tool_check_reason_ls,
                        "tool_instruction_ls": tool_instruction_ls,
                    },
                    "check": 0
                }, ensure_ascii=False)
                f.write(line + '\n')

            print(final_answer)
            update_progress(progress_file, i + 1)
            pbar.update(1)


def task_execution_oh(data_type, start_index, total_files,
                      retrieval_num, ind, model_name, dataset,
                      Tool_dic, test_data, progress_file):
    with tqdm(total=total_files, desc="Processing files", initial=start_index) as pbar:
        for i, data in enumerate(test_data[start_index:], start=start_index):
            answer_ls = []
            question = data["question"]
            print(question)
            task_ls = [{"task": question}]
            answer_task = []
            tool_instruction_ls = []
            api_result_ls = []
            call_result_ls = []
            tool_check_reason_ls = []
            for task_dic in task_ls:
                task = task_dic['task']
                print("Do need tool.")
                tool_used = []
                depend_id = [1]
                for r in range(retrieval_num):
                    tool_id, api_result, call_result, tool_instruction, API_instruction = retrieval(task, Tool_dic,
                                                                                                    dataset,
                                                                                                    tool_used, ind,
                                                                                                    model_name)
                    if len(str(call_result)) > 5000:
                        call_result = str(call_result)[:5000]
                    answer = answer_generation(task, API_instruction, call_result, model_name)

                    check_index = 1
                    if str(call_result).strip() == '-1' or str(call_result).strip() == '':
                        check_index = -1
                    if check_index == 1:
                        answer_task.append({'task': task, 'answer': answer})
                        tool_instruction_ls.append(tool_instruction)
                        api_result_ls.append(api_result)
                        call_result_ls.append(call_result)
                        break
                    else:
                        answer_ls.append({'task': task, 'answer': answer})
                        try:
                            tool_used.append(str(tool_id["ID"]))
                        except:
                            continue
                        print('****Try Again****')

            final_answer = answer_summarize(question, answer_task, model_name)
            check_index = answer_check(question, final_answer, model_name)
            ind = ind + 1
            with open(f"FuncQA_{data_type}_{model_name}_easytool.jsonl", 'a+', encoding='utf-8') as f:
                line = json.dumps({
                    "ID": ind,
                    "question": question,
                    "final_answer": final_answer,
                    "subtask": task_ls,
                    "answer_subtask": answer_task,
                    "answer_wrong": answer_ls,
                    "check_index": check_index,
                    "execute_log": {
                        "api_result_ls": api_result_ls,
                        "call_result_ls": call_result_ls,
                        "tool_check_reason_ls": tool_check_reason_ls,
                        "tool_instruction_ls": tool_instruction_ls,
                    },
                    "check": 0
                }, ensure_ascii=False)
                f.write(line + '\n')

            print(final_answer)
            update_progress(progress_file, i + 1)
            pbar.update(1)

